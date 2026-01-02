print("[MessageVerifier] module loaded")
def _split_keywords(text: str):
    if not isinstance(text, str):
        return []
    return [t.strip() for t in text.split(",") if t.strip()]


def check_banned(message: str, banned: str):
    hits = [k for k in _split_keywords(banned) if k in message]
    if hits:
        return f"banned hit: {hits}"
    return None


def check_must_include(message: str, must_include: str):
    keywords = _split_keywords(must_include)
    if not keywords:
        return None
    if not any(k in message for k in keywords):
        return f"must_include miss: {keywords}"
    return None


def check_viewpoint(message: str, viewpoint: str):
    keywords = _split_keywords(viewpoint)
    if not keywords:
        return None
    if not any(k in message for k in keywords):
        return f"viewpoint miss: {keywords}"
    return None


def verify_brand_rules(message: str, rule_row: dict):
    errors = []

    e = check_banned(message, rule_row.get("banned", ""))
    if e: errors.append(e)

    e = check_must_include(message, rule_row.get("must_include", ""))
    if e: errors.append(e)

    e = check_viewpoint(message, rule_row.get("viewpoint", ""))
    if e: errors.append(e)

    print("[MessageVerifier] verify_brand_rules called")
    return errors