"""AEF-005: multi-step planning benchmark with real remote Qwen3-4B.

48 cases (6 goal families x 8 variants), 4 strategies, seeded interleaving.
Read-only synthetic world; no filesystem writes except report output.
"""
from __future__ import annotations
import argparse, json, random, time, statistics
from pathlib import Path
from collections import deque
from dataclasses import dataclass
from typing import FrozenSet

@dataclass(frozen=True)
class Operator:
    name: str
    requires: FrozenSet[str]
    adds: FrozenSet[str]
    removes: FrozenSet[str] = frozenset()

def plan(initial, goals, operators, *, max_depth=14, max_states=30000):
    start=frozenset(initial)
    target=frozenset(goals)
    if target <= start:
        return []
    ordered=tuple(sorted(operators,key=lambda o:o.name))
    q=deque([(start,())])
    visited={start}
    while q:
        state,path=q.popleft()
        if len(path)>=max_depth:
            continue
        for op in ordered:
            if not op.requires<=state:
                continue
            new=(state-op.removes)|op.adds
            if new==state or new in visited:
                continue
            route=path+(op.name,)
            if target<=new:
                return list(route)
            visited.add(new)
            if len(visited)>max_states:
                raise ValueError("state budget exceeded")
            q.append((new,route))
    return None

def verify(initial,goals,operators,path):
    state=frozenset(initial)
    d={o.name:o for o in operators}
    if not isinstance(path,list) or len(path)>32:
        return False
    for name in path:
        op=d.get(name)
        if op is None or not op.requires<=state:
            return False
        state=(state-op.removes)|op.adds
    return frozenset(goals)<=state

def simulate(initial,operators,path):
    state=frozenset(initial)
    indexed={o.name:o for o in operators}
    steps=[]
    for name in path:
        op=indexed.get(name)
        if op is None or not op.requires<=state:
            return {"valid":False,"trace":steps,"final":sorted(state)}
        state=(state-op.removes)|op.adds
        steps.append({"action":name,"state":sorted(state)})
    return {"valid":True,"trace":steps,"final":sorted(state)}




import os, urllib.request, urllib.error
class GroqModel:
    def __init__(self):
        self.last_request_at=0
    def wait(self):
        delay=2.2-(time.monotonic()-self.last_request_at)
        if delay>0: time.sleep(delay)
    def complete(self, name, prompt, *, max_tokens=512):
        key=os.environ.get("GROQ_API_KEY")
        if not key: raise RuntimeError("GROQ_API_KEY unavailable inside Actions")
        data=json.dumps({"model":"openai/gpt-oss-120b","messages":[{"role":"user","content":prompt}],
                         "temperature":0,"max_completion_tokens":max_tokens,"reasoning_effort":"low"}).encode()
        req=urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",data=data,
              headers={"Authorization":"Bearer "+key,"Content-Type":"application/json",
                       "User-Agent":"buddie-knotrun-benchmark/1"},method="POST")
        self.last_request_at=time.monotonic()
        try:
            with urllib.request.urlopen(req,timeout=45) as response:
                result=json.load(response)
        except urllib.error.HTTPError as e:
            raise RuntimeError("Groq HTTP "+str(e.code)) from None
        return {"content":result["choices"][0]["message"].get("content") or "",
                "usage":result.get("usage",{})}

FAMILIES = {
    "publish": (["Connect network", "Fetch signing key", "Authenticate publisher",
                 "Load publication", "Validate publication", "Publish content"],
                ["online", "signing_key", "authenticated", "loaded", "validated", "published"],
                ["Make the content public", "Publish the release", "Send the publication live",
                 "Make this visible to everyone", "Release the material", "Push the publication",
                 "Expose the validated data publicly", "Finalize the public release"]),
    "archive": (["Locate package", "Request archive access", "Read package",
                 "Check package integrity", "Archive package"],
                ["located","access","read","checked","archived"],
                ["Archive the package","Put the package into storage","Store the checked package",
                 "Preserve these materials safely","Keep the package for future retrieval",
                 "Create the archive","Retain the validated package","Put this into long term storage"]),
    "deliver": (["Identify route", "Reserve vehicle", "Load shipment", "Deliver shipment"],
                ["route","vehicle","loaded","delivered"],
                ["Deliver the parcel","Get the shipment to its destination","Send the cargo",
                 "Make sure the parcel reaches its recipient","Complete this delivery",
                 "Transport the shipment successfully","Finish shipping the parcel",
                 "Hand over the cargo at destination"]),
    "report": (["Discover logs","Acquire audit permission","Parse logs",
                "Summarize findings","Send findings"],
               ["logs","audit_access","parsed","summarized","reported"],
               ["Send the audit report","Report the findings","Submit the analysis",
                "Communicate the audit outcome","Write and transmit a summary",
                "Get the final findings to the reviewer","Finish the log investigation report",
                "Provide the audit results to the requester"]),
    "deploy": (["Inspect manifest","Build artifact","Run checks","Stage artifact","Deploy artifact"],
                ["inspected","built","tested","staged","deployed"],
                ["Deploy the update","Release the new build","Ship the tested artifact",
                 "Make the service use the new version","Roll out the tested build",
                 "Move the build into production","Finish release rollout",
                 "Install the new release in the service"]),
    "unlock": (["Locate credential","Verify identity","Grant permission","Unlock gate"],
                ["credential","identity","permission","unlocked"],
                ["Unlock the gate","Open the secured entrance","Get the door opened",
                 "Gain authorized entry","Enable access to the locked gate",
                 "Allow the entry door to open","Complete the authorized unlocking",
                 "Open the locked entrance"]),
}
# Goals not inferred from the eval labels in the classifier.
GOALS = {k: vals[1][-1] for k,vals in FAMILIES.items()}
RULES = {
    "publish": ("publish","publication","public","release the material"),
    "archive": ("archive","storage","retain","preserve"),
    "deliver": ("deliver","shipment","shipping","cargo"),
    "report": ("audit","report","findings","analysis"),
    "deploy": ("deploy","build","rollout","service"),
    "unlock": ("unlock","gate","door","entry"),
}
UNREACHABLE_VARIANT=5   # prerequisite capability missing
CHANGED_VARIANT=6       # state perturbation, compensate using alternative operator
MAX_TOKENS=512

def world(family,variant):
    labels,facts,_=FAMILIES[family]
    initial={"start"}
    operators=[]
    required="start"
    for i,(label,fact) in enumerate(zip(labels,facts)):
        op=Operator("step_%s_%s"%(family,i+1),frozenset({required}),
                    frozenset({fact}))
        operators.append(op)
        required=fact
    # Eight distractors irrelevant to the requested goal.
    for i in range(8):
        operators.append(Operator(f"noop_{i+1}",frozenset({"start"}),
                                  frozenset({f"distractor_{i+1}"})))
    if variant==UNREACHABLE_VARIANT:
        operators=[op for op in operators if op.name!=f"step_{family}_2"]
    if variant==CHANGED_VARIANT:
        # A missing normal operator is replaced by a valid alternate path.
        operators=[op for op in operators if op.name!=f"step_{family}_2"]
        operators.extend([
            Operator("recover_alt_1",frozenset({"start"}),frozenset({"alt_ready"})),
            Operator("recover_alt_2",frozenset({"alt_ready"}),frozenset({facts[1]})),
        ])
    return initial,operators

def dataset(seed=37):
    samples=[]
    for family, (labels,facts,phrases) in FAMILIES.items():
        for variant in range(8):
            initial,ops=world(family,variant)
            samples.append({"id":family+"_"+str(variant),"family":family,
                "request":phrases[variant],"target":GOALS[family],
                "unreachable":variant==UNREACHABLE_VARIANT,
                "changed":variant==CHANGED_VARIANT,
                "initial":initial,"operators":ops})
    random.Random(seed).shuffle(samples)
    return samples

def route_heuristic(request):
    t=request.lower()
    hits=[k for k,patterns in RULES.items() if any(p in t for p in patterns)]
    return GOALS[hits[0]] if len(hits)==1 else None

def format_ops(ops):
    return [{"name":o.name,"requires":sorted(o.requires),
            "adds":sorted(o.adds),"removes":sorted(o.removes)}
            for o in ops]

def goal_prompt(sample):
    return "/no_think\n"+json.dumps({"instruction":"Choose one goal matching the user request. Return only JSON with the single key goal, no explanation.",
        "allowed_goals":GOALS,"request":sample["request"]},separators=(",",":"))

def full_prompt(sample):
    return "/no_think\n"+json.dumps({"instruction":"Plan actions to satisfy the user request. Return JSON only: {\"actions\":[\"operator name\",...]} or {\"unreachable\":true} if not possible. Use only listed operators, enforce requires/adds/removes. No explanation.",
        "initial_facts":sorted(sample["initial"]),
        "operators":format_ops(sample["operators"]),
        "request":sample["request"],
        "goal_vocab":GOALS},separators=(",",":"))

def parse_goal(text):
    try:
        data=json.loads(text)
        if not isinstance(data,dict) or set(data)!={"goal"}:return None
        return GOALS.get(data["goal"],data["goal"] if data["goal"] in GOALS.values() else None) if isinstance(data["goal"],str) else None
    except (TypeError, ValueError):
        return None

def parse_actions(text):
    try:
        data=json.loads(text)
        if not isinstance(data,dict):return None
        if data=={"unreachable":True}:return None
        if set(data)!={"actions"} or not isinstance(data["actions"],list):return []
        if not all(isinstance(s,str) for s in data["actions"]):return []
        return data["actions"]
    except (TypeError, ValueError):
        return []

def infer(model,prompt):
    if hasattr(model,'wait'): model.wait()
    start=time.perf_counter()
    try:
        reply=model.complete("qwen",prompt,max_tokens=MAX_TOKENS)
        usage=reply.get("usage") or {}
        return reply["content"],{
            "call":1,"tokens":usage.get("total_tokens"),
            "prompt_tokens":usage.get("prompt_tokens"),
            "completion_tokens":usage.get("completion_tokens"),
            "seconds":round(time.perf_counter()-start,4),
            "error":None}
    except Exception as exc:
        return None,{"call":1,"tokens":None,"prompt_tokens":None,
            "completion_tokens":None,"seconds":round(time.perf_counter()-start,4),
            "error":type(exc).__name__}

def assess(sample,path,goal=None):
    original=sample["target"]
    if goal is not None and goal!=original:
        return False,"wrong_goal"
    reachable=plan(sample["initial"],[original],sample["operators"]) is not None
    if not reachable:
        return (path is None),("passed_unreachable" if path is None else "false_positive")
    if path is None:
        return False,"false_unreachable"
    valid=verify(sample["initial"],[original],sample["operators"],path)
    return valid,"passed" if valid else "invalid_plan"

def measure_case(model,sample,method):
    start=time.perf_counter()
    evidence={"call":0,"tokens":0,"prompt_tokens":0,"completion_tokens":0,
              "seconds":0.0,"error":None}
    guessed_goal=None
    if method=="full":
        text,evidence=infer(model,full_prompt(sample))
        path=parse_actions(text) if text is not None else []
    else:
        if method=="exact":
            guessed_goal=sample["target"]  # privileged oracle, upper bound
        elif method=="adaptive":
            guessed_goal=route_heuristic(sample["request"])
        if guessed_goal is None:
            text,evidence=infer(model,goal_prompt(sample))
            guessed_goal=parse_goal(text) if text is not None else None
        path=(plan(sample["initial"],[guessed_goal],sample["operators"])
              if guessed_goal is not None else [])
    success,reason=assess(sample,path,guessed_goal if method!="full" else None)
    if evidence["error"]:reason=evidence["error"];success=False
    return {"id":sample["id"],"family":sample["family"],
        "variant":int(sample["id"].split("_")[-1]),
        "changed":sample["changed"],"unreachable":sample["unreachable"],
        "method":method,"success":success,"reason":reason,
        "steps":len(path) if path is not None else None,
        "model_calls":evidence["call"],"tokens":evidence["tokens"],
        "prompt_tokens":evidence["prompt_tokens"],
        "completion_tokens":evidence["completion_tokens"],
        "inference_s":evidence["seconds"],
        "elapsed_s":round(time.perf_counter()-start,4)}

def summarize(rows):
    grouped={}
    for method in ("exact","delegated","adaptive","full"):
        records=[r for r in rows if r["method"]==method]
        token_values=[r["tokens"] for r in records if r["tokens"] is not None]
        grouped[method]={
            "total":len(records),
            "success":sum(r["success"] for r in records),
            "calls":sum(r["model_calls"] for r in records),
            "tokens":sum(token_values),
            "tokens_missing":sum(r["tokens"] is None for r in records),
            "prompt_tokens":sum((r["prompt_tokens"] or 0) for r in records),
            "completion_tokens":sum((r["completion_tokens"] or 0) for r in records),
            "inference_s":round(sum(r["inference_s"] for r in records),3),
            "elapsed_s":round(sum(r["elapsed_s"] for r in records),3),
            "unreachable_correct":sum(r["success"] for r in records if r["unreachable"]),
            "changed_correct":sum(r["success"] for r in records if r["changed"]),
            "errors":{error:sum(r["reason"]==error for r in records) for error in sorted({r["reason"] for r in records if not r["success"]})}
        }
    return grouped

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",required=True)
    p.add_argument("--seed",type=int,default=37)
    p.add_argument("--dry",action="store_true")
    p.add_argument("--modes",nargs="+",default=["exact","delegated","adaptive","full"])
    args=p.parse_args()
    data=dataset(args.seed)
    if args.dry:
        for sample in data[:4]:print(sample["id"],sample["request"],plan(sample["initial"],[sample["target"]],sample["operators"]))
        return
    model=GroqModel()
    rng=random.Random(args.seed+7)
    rows=[]
    for idx,sample in enumerate(data):
        order=args.modes[:]
        rng.shuffle(order)
        for method in order:
            result=measure_case(model,sample,method)
            rows.append(result)
            print(f"{idx+1}/{len(data)} {sample['id']} {method} {'PASS' if result['success'] else 'FAIL'} {result['reason']} tokens={result['tokens']}",flush=True)
    output={"schema":"knotrun.aef005-benchmark/v1","seed":args.seed,
        "model":"Groq openai/gpt-oss-120b via GitHub Actions",
        "notes":["synthetic state transitions; no shell/filesystem mutations","Exact uses supplied correct target; Adaptive router uses text patterns, not ground truth","single run, randomized order per case; no repeated inference trials"],
        "summary":summarize(rows),"rows":rows}
    out=Path(args.output);out.parent.mkdir(exist_ok=True,parents=True)
    out.write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print("SUMMARY",json.dumps(output["summary"]),flush=True)
    print("OUTPUT",out,flush=True)
if __name__=="__main__":main()

