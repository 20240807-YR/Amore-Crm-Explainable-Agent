from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

PERSONA_BRAND_WEIGHT: Dict[str, Dict[str, float]] = {
    "persona_1": {
        "프리메라": 1.1,
        "라네즈": 1.1,
    },
    "persona_3": {
        "설화수": 1.25,
        "헤라": 1.2,
        "아이오페": 1.15,
        "프리메라": 0.7,
    },
    "persona_6": {
        "마몽드": 1.2,
        "에뛰드": 1.15,
        "이니스프리": 1.1,
        "프리메라": 0.75,
    },
}


class ProductSelector:
    """Selects the best product from a candidate list.

    NOTE:
    - Controller currently instantiates `ProductSelector()` with no args.
      To keep interface compatibility, constructor args are optional.
    - DataFrame wiring can be done via constructor OR `configure()`.
    """

    def __init__(
        self,
        df: Optional[Any] = None,
        name_col: Optional[str] = None,
        brand_col: Optional[str] = None,
    ):
        self.df = df
        self.name_col = name_col
        self.brand_col = brand_col

    def configure(self, df: Any, name_col: str, brand_col: str) -> None:
        self.df = df
        self.name_col = name_col
        self.brand_col = brand_col

    @staticmethod
    def _s(x: Any) -> str:
        return "" if x is None else str(x).strip()

    def apply_brand_boost(self, persona_keywords: list, brand_name: str, original_score: float) -> float:
        """
        [비즈니스 로직: 메이크온 킬 스위치]
        """
        # 1. 브랜드명 정규화 (공백 제거 + 안전장치)
        raw_name = "" if brand_name is None else str(brand_name)
        b_name = raw_name.replace(" ", "").strip()

        # 2. 키워드 통합
        keywords_str = " ".join(persona_keywords or [])

        # 3. 디버깅용 로그 (필요 시 주석 해제)
        # print(f"[DEBUG] Brand(raw={raw_name!r} -> norm={b_name!r}) | score={original_score:.4f} | kw={keywords_str[:60]}...")

        # ---------------------------------------------------------
        # 🚨 1. 메이크온(MakeON) 조건부 사형 선고
        # ---------------------------------------------------------
        if ("메이크온" in b_name) or ("MakeON" in b_name) or ("MAKEON" in b_name.upper()):
            # 살려줄 조건: '기기/디바이스/전문/스페셜' 니즈가 명확할 때만
            allow_keywords = ["기기", "디바이스", "전문", "스페셜", "집중관리", "집중", "홈케어"]
            if not any(k in keywords_str for k in allow_keywords):
                # 조건 불만족 시 점수 95% 삭감 (사실상 사망)
                return original_score * 0.05

        # ---------------------------------------------------------
        # ✅ 2. 타 브랜드 강력 부스팅 (경쟁자 키우기)
        # ---------------------------------------------------------
        # 민감/트러블/지성/수부지 -> 더마/기능성 라인
        if any(k in keywords_str for k in ["민감", "홍조", "장벽", "따가움", "진정", "트러블", "피지", "수부지", "지성", "모공"]):
            if b_name in ["에스트라", "일리윤", "순정", "라네즈", "프리메라", "마몽드", "한율", "이니스프리"]:
                return original_score * 2.0

        # 안티에이징/프리미엄 -> 프리미엄 브랜드
        if any(k in keywords_str for k in ["주름", "탄력", "노화", "안티에이징", "리프팅", "속건조", "광채"]):
            if b_name in ["설화수", "헤라", "아이오페", "바이탈뷰티"]:
                return original_score * 1.5

        return original_score

    def select_best_product(self, results, row) -> Tuple[Optional[str], float]:
        if self.df is None or not self.name_col or not self.brand_col:
            raise TypeError(
                "ProductSelector is not configured. Provide df/name_col/brand_col "
                "via constructor or call configure(df, name_col, brand_col) before select_best_product()."
            )

        best_score = -1.0
        best_name: Optional[str] = None

        # results: iterable of product identifiers (names)
        for name in results:
            sub_df = self.df[self.df[self.name_col] == name]
            if sub_df.empty:
                continue

            # brand string
            b = self._s(sub_df.iloc[0][self.brand_col])

            # precomputed similarity columns (0.0 ~ 1.0). If absent, treat as 0.
            sim_benefit = float(sub_df.iloc[0]["benefit_score"]) if "benefit_score" in sub_df.columns else 0.0
            sim_identity = float(sub_df.iloc[0]["identity_score"]) if "identity_score" in sub_df.columns else 0.0
            sim_emotion = float(sub_df.iloc[0]["emotion_score"]) if "emotion_score" in sub_df.columns else 0.0

            # Benefit 중심 가중치(0.6/0.3/0.1)
            final_score = (0.6 * sim_benefit) + (0.3 * sim_identity) + (0.1 * sim_emotion)

            persona_id = row.get("persona_id") if isinstance(row, dict) else None
            weight = PERSONA_BRAND_WEIGHT.get(persona_id, {}).get(b, 1.0)
            weighted_score = final_score * weight

            # Persona keywords for business rules (concise + stable)
            persona_keywords: List[str] = []
            if isinstance(row, dict):
                for k in [
                    "persona_name",
                    "preference",
                    "shopping_pattern",
                    "lifestyle",
                    "skin_type",
                    "skin_concern",
                    "allergy_sensitivity",
                    "texture_preference",
                    "finish_preference",
                    "scent_preference",
                    "time_of_use",
                    "seasonality",
                    "environment_context",
                ]:
                    v = row.get(k)
                    if v is None:
                        continue
                    # split common separators to widen match surface
                    s = self._s(v)
                    if not s:
                        continue
                    for token in s.replace("/", ",").replace(";", ",").split(","):
                        t = token.strip()
                        if t:
                            persona_keywords.append(t)

            weighted_score = self.apply_brand_boost(persona_keywords=persona_keywords, brand_name=b, original_score=weighted_score)

            if weighted_score > best_score:
                best_score = weighted_score
                best_name = name

        return best_name, float(best_score)