"""받침에 따라 모양이 바뀌는 조사를 코드로 검사한다.

모델이 조사를 고칠 때 받침과 맞지 않는 형태('영화을')를 내거나, 고친 조사와 다른 조사의 자료를
근거로 붙이는('영화가'에 을/를 자료) 일이 실제로 있었다. 둘 다 규칙으로 판정할 수 있다.
"""
from __future__ import annotations

# (받침 뒤, 받침 없음 뒤). '으로'를 '로'보다 먼저 봐야 '집으로'를 '집으'+'로'로 자르지 않는다.
PARTICLE_PAIRS = [("으로", "로"), ("을", "를"), ("이", "가"), ("은", "는"), ("과", "와")]
# 조사 한 쌍만 다루는 문법 자료. 이 밖의 자료는 검사하지 않는다.
PARTICLE_ENTRIES = {"p-object": ("을", "를"), "p-subject": ("이", "가"), "p-topic": ("은", "는"),
                    "p-ro": ("으로", "로")}


def right_form(before: str, pair: tuple[str, str]) -> str | None:
    """before 글자 뒤에 올 조사 형태. 한글 음절이 아니면 None."""
    if not "가" <= before <= "힣":
        return None
    final = (ord(before) - ord("가")) % 28  # 0이면 받침 없음, 8이면 ㄹ
    return pair[1] if final == 0 or (pair[0] == "으로" and final == 8) else pair[0]


def split_particle(word: str) -> tuple[str, str, tuple[str, str]] | None:
    """'영화를' → ('영화', '를', ('을', '를')). 끝이 받침 쌍 조사가 아니면 None."""
    word = word.strip()
    for pair in PARTICLE_PAIRS:
        for particle in pair:
            stem = word[:-len(particle)]
            if word.endswith(particle) and stem and "가" <= stem[-1] <= "힣":
                return stem, particle, pair
    return None


def _suggested(expression: str, suggestion: str) -> tuple[str, str, tuple[str, str]] | None:
    """제안 끝의 조사. 원문에서 그 글자가 낱말의 일부였으면('사과' → '사과') 조사로 보지 않는다."""
    split = split_particle(suggestion)
    if split is None:
        return None
    stem, particle, _ = split
    expression = expression.strip()
    if not expression.startswith(stem) or expression[len(stem):].startswith(particle):
        return None
    return split


def fix_particle_form(expression: str, suggestion: str) -> str:
    """제안의 조사 형태를 앞 글자 받침에 맞춘다('영화을' → '영화를')."""
    split = _suggested(expression, suggestion)
    if split is None:
        return suggestion
    stem, particle, pair = split
    return stem + (right_form(stem[-1], pair) or particle)


def particle_conflict(expression: str, suggestion: str, grammar_id: str) -> bool:
    """근거 자료가 다루는 조사가 고친 조사와도, 원래 쓴 조사와도 다르면 True."""
    entry_pair = PARTICLE_ENTRIES.get(grammar_id)
    split = _suggested(expression, suggestion)
    if entry_pair is None or split is None:
        return False
    written = split_particle(expression)
    return entry_pair not in {split[2], written[2] if written else None}
