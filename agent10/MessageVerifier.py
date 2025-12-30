def load_brand_rules(csv_path):
    df = pd.read_csv(csv_path)
    rules = {}
    for _, row in df.iterrows():
        brand = row["brand"]
        rules.setdefault(brand, []).append(row)
    return rules

def check_banned(message, banned_rule):
    for keyword in banned_rule.split(","):
        if keyword.strip() in message:
            return f"금지 표현 포함: {keyword}"
    return None

def check_tone_guard(message, tone_guard):
    # 단순 1차: 핵심 관점 키워드 포함 여부
    key_terms = ["균형", "부담", "리듬", "기본", "지속"]  # 브랜드별로 다르게
    hit = sum(1 for k in key_terms if k in message)
    if hit == 0:
        return "브랜드 톤 관점 이탈"
    return None

errors = []
err = check_banned(body, rule["banned"])
if err: errors.append(err)

err = check_tone_guard(body, rule["tone_guard"])
if err: errors.append(err)