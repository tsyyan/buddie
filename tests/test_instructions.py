"""The format instructions clients get without buddie's skill (initialize.instructions, tool descriptions): their
examples must be what the parser checks, or a model that follows them hands in a report buddie cannot read."""
from __future__ import annotations

from buddie import mcp, remote
from buddie.verbatim.store import Store
from buddie.verify import verify

PAGE = ("<html><body><h1>Статья 2.10 КоАП РФ</h1><p>Юридическое лицо, присоединившее другое юридическое лицо, "
        "подлежит ответственности за совершение административного правонарушения, совершённого присоединённым "
        "юридическим лицом.</p>"
        + "".join(f"<p>Пункт {n} комментария: при реорганизации в форме присоединения обязанности переходят к "
                  f"правопреемнику, и суд проверяет дату внесения записи в реестр, вариант {n}.</p>" for n in range(60))
        + "</body></html>").encode("utf-8")
URL = "https://www.zakonrf.info/koap/2.10/"


def test_the_quote_example_is_checked(tmp_path):
    store = Store(tmp_path / "store")
    store.add(URL, PAGE, content_type="text/html; charset=utf-8")
    receipt = verify(mcp.QUOTE_EXAMPLE, store=store.root, fetch=False, mandate=False)
    (quote,) = receipt["predicate"]["quotes"]
    assert quote["url"] == URL and quote["verdict"] == "FOUND"
    assert receipt["predicate"]["outcome"] == "PASS"
    altered = mcp.QUOTE_EXAMPLE.replace("подлежит ответственности", "освобождается от ответственности")
    assert verify(altered, store=store.root, fetch=False, mandate=False)["predicate"]["outcome"] == "FAIL"


def test_the_anchor_example_is_two_anchors():
    anchors = verify(mcp.ANCHOR_EXAMPLE, repos=[], fetch=False, github=None, mandate=False)["predicate"]["anchors"]
    assert sorted(a["kind"] for a in anchors) == ["ci", "pr"]


def test_clients_get_the_format():
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
    local, hosted = mcp.handle(init)["result"]["instructions"], remote.handle(init)["result"]["instructions"]
    assert local == mcp.INSTRUCTIONS and mcp.QUOTE_EXAMPLE in local and "EMPTY" in local
    assert hosted == remote.INSTRUCTIONS and remote.REMOTE_SCOPE in hosted and mcp.QUOTE_EXAMPLE in hosted
    verify_tool = next(t for t in remote.tools() if t["name"] == "verify_report")
    assert mcp.QUOTE_EXAMPLE in verify_tool["description"] and "GAPS" in verify_tool["description"]
