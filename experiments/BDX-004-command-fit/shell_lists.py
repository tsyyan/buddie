"""Small quote-aware shell lexer; it retains offsets and never evaluates expansions."""
from dataclasses import dataclass
from syntax import family


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int
    operator: bool = False
    closed: bool = True


def lex(text, shell='sh'):
    tokens, i = [], 0
    powershell = family(shell) == 'powershell'
    operators = ('&&', '||', ';;', ';', '\n', '(', ')', '{', '}', '|')
    while i < len(text):
        if text[i].isspace() and text[i] != '\n':
            i += 1
            continue
        if text[i] == '#' and (i == 0 or text[i - 1].isspace()):
            end = text.find('\n', i)
            i = len(text) if end < 0 else end
            continue
        op = next((op for op in operators if text.startswith(op, i)), None)
        if op:
            tokens.append(Token(op, i, i + len(op), True))
            i += len(op)
            continue
        start, quote = i, None
        while i < len(text):
            char = text[i]
            escape = '`' if powershell else '\\'
            if char == escape and quote != "'":
                i = min(i + 2, len(text))
                continue
            if quote:
                if char == quote:
                    if powershell and i + 1 < len(text) and text[i + 1] == quote:
                        i += 2
                        continue
                    quote = None
                i += 1
                continue
            if char in ('"', "'") or (char == '`' and not powershell):
                quote = char
                i += 1
                continue
            if char.isspace() or any(text.startswith(op, i) for op in operators):
                break
            i += 1
        tokens.append(Token(text[start:i], start, i, closed=quote is None))
    return tokens


def split_list(text, shell):
    """(simple text, following connector); nested expressions remain opaque."""
    separators = {';', '\n', '&&', '||'} if family(shell) == 'posix' else {';', '\n'}
    if family(shell) not in ('posix', 'powershell'):
        return [(text, '')], False
    out, depth, start, found = [], 0, 0, False
    for token in lex(text, shell):
        if token.operator and token.text in ('(', '{'):
            depth += 1
        elif token.operator and token.text in (')', '}'):
            depth = max(0, depth - 1)
        elif token.operator and token.text in separators and not depth:
            found = True
            if part := text[start:token.start].strip():
                out.append((part, token.text))
            start = token.end
    if part := text[start:].strip():
        out.append((part, ''))
    return out, found
