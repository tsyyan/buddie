"""A bounded structural POSIX parser; native shell parsers still decide syntax."""
import re
from shell_lists import lex

OPENERS = {'if', 'for', 'while', 'until', 'case'}
SEPARATORS = {';', '\n', '&&', '||'}


class Incomplete(ValueError):
    pass


def has_control(text):
    prior = ';'
    for token in lex(text):
        if token.text in OPENERS and prior in SEPARATORS | {'then', 'else', 'do'}:
            return True
        prior = token.text
    return False


class Parser:
    def __init__(self, text):
        self.text, self.tokens, self.i = text, lex(text), 0

    def peek(self):
        return self.tokens[self.i].text if self.i < len(self.tokens) else None

    def expect(self, word):
        if self.peek() is None:
            raise Incomplete(f'missing {word}')
        if self.peek() != word:
            raise ValueError(f'expected {word}')
        self.i += 1

    def sequence(self, stops=(), stop_ops=(), depth=0):
        if depth > 32:
            raise ValueError('structure nesting outside the supported subset')
        nodes = []
        while self.peek() is not None:
            if self.peek() in stops or self.peek() in stop_ops:
                break
            if self.peek() in (';', '\n'):
                self.i += 1
                continue
            start = self.i
            if self.peek() in OPENERS:
                node = self.structure(depth + 1)
            else:
                parens = 0
                while self.peek() is not None:
                    word = self.peek()
                    if not parens and word in SEPARATORS | set(stop_ops):
                        break
                    if word in ('(', '{'):
                        parens += 1
                    elif word in (')', '}'):
                        parens = max(0, parens - 1)
                    self.i += 1
                if self.i == start:
                    raise ValueError('unsupported separator')
                node = dict(kind='simple', text=self.text[self.tokens[start].start:self.tokens[self.i - 1].end])
            node['after'] = ''
            if self.peek() in SEPARATORS:
                node['after'] = self.peek()
                self.i += 1
            nodes.append(node)
        return nodes

    def structure(self, depth):
        start, kind, groups, uncertain = self.i, self.peek(), [], False
        self.i += 1
        if kind == 'if':
            while True:
                condition = self.sequence({'then'}, depth=depth)
                self.expect('then')
                body = self.sequence({'elif', 'else', 'fi'}, depth=depth)
                groups.append(dict(condition=condition, body=body))
                if self.peek() == 'elif':
                    self.i += 1
                    continue
                if self.peek() == 'else':
                    self.i += 1
                    groups.append(dict(condition=[], body=self.sequence({'fi'}, depth=depth)))
                self.expect('fi')
                break
        elif kind in ('while', 'until'):
            condition = self.sequence({'do'}, depth=depth)
            self.expect('do')
            groups.append(dict(condition=condition, body=self.sequence({'done'}, depth=depth)))
            self.expect('done')
        elif kind == 'for':
            header = []
            while self.peek() is not None and self.peek() not in (';', '\n'):
                header.append(self.peek())
                self.i += 1
            if not header or not re.fullmatch(r'[A-Za-z_]\w*', header[0]):
                uncertain = True
            if any('$' in t or '`' in t or t in ('(', ')') for t in header):
                uncertain = True  # dynamic iteration lists may execute additional commands
            while self.peek() in (';', '\n'):
                self.i += 1
            self.expect('do')
            groups.append(dict(condition=[], body=self.sequence({'done'}, depth=depth)))
            self.expect('done')
        else:
            subject = self.peek()
            if subject is None:
                raise Incomplete('case subject')
            uncertain = '$(' in subject or '`' in subject
            self.i += 1
            self.expect('in')
            while True:
                while self.peek() in (';', '\n'):
                    self.i += 1
                if self.peek() == 'esac':
                    self.i += 1
                    break
                while self.peek() not in (')', None):
                    if '$(' in self.peek() or '`' in self.peek() or self.peek() == '$':
                        uncertain = True
                    self.i += 1  # patterns are data, not commands
                self.expect(')')
                body = self.sequence({'esac'}, {';;'}, depth)
                groups.append(dict(condition=[], body=body))
                if self.peek() == ';;':
                    self.i += 1
                elif self.peek() != 'esac':
                    raise Incomplete('case arm terminator')
        return dict(kind=kind, text=self.text[self.tokens[start].start:self.tokens[self.i - 1].end],
                    groups=groups, uncertain=uncertain)


def parse(text):
    parser = Parser(text)
    nodes = parser.sequence()
    if parser.peek() is not None:
        raise ValueError('unconsumed structural tokens')
    return nodes


def complete(text):
    try:
        parse(text)
        return True
    except Incomplete:
        return False
    except ValueError:
        # Keep malformed structures together until their apparent closing keyword.
        tokens = lex(text)
        return bool(tokens and tokens[-1].text in ('fi', 'done', 'esac'))
