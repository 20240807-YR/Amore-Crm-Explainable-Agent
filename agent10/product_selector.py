
from __future__ import annotations

import re

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

    @staticmethod
    def _normalize_brand(x: Any) -> str:
        """Normalize brand string for strict matching.

        목적:
        - 데이터 내 표기 흔들림(공백/괄호/영문 병기/대소문자) 때문에 hard filter가 뚫리는 현상 차단
        - 'MakeON'/'메이크온', 'Primera'/'프리메라' 같은 동의 표기를 하나의 canonical 값으로 수렴
        """
        raw = "" if x is None else str(x)
        s = raw.strip()
        if not s:
            return ""

        # 1) 공백 제거
        s_nospace = s.replace(" ", "")

        # 2) 괄호/특수문자 제거(영문 병기 포함 케이스 정리)
        #    - 한글/영문/숫자만 남기고 나머지는 제거
        s_clean = re.sub(r"[^0-9A-Za-z가-힣]", "", s_nospace)

        upper = s_clean.upper()

        # 3) Canonical alias mapping (부분 포함도 허용)
        #    - 제품/데이터에서 '프리메라Primera'처럼 붙어서 들어오는 케이스도 처리
        if ("MAKEON" in upper) or ("메이크온" in s_clean):
            return "메이크온"
        if ("PRIMERA" in upper) or ("프리메라" in s_clean):
            return "프리메라"
        if ("LANEIGE" in upper) or ("라네즈" in s_clean):
            return "라네즈"
        if ("HERA" in upper) or ("헤라" in s_clean):
            return "헤라"
        if ("SULWHASOO" in upper) or ("설화수" in s_clean):
            return "설화수"
        if ("INNISFREE" in upper) or ("이니스프리" in s_clean):
            return "이니스프리"
        if ("ETUDE" in upper) or ("에뛰드" in s_clean):
            return "에뛰드"
        if ("MAMONDE" in upper) or ("마몽드" in s_clean):
            return "마몽드"
        if ("ILLIYOON" in upper) or ("일리윤" in s_clean):
            return "일리윤"
        if ("AESTURA" in upper) or ("에스트라" in s_clean):
            return "에스트라"
        if ("ODYSSEY" in upper) or ("오딧세이" in s_clean):
            return "오딧세이"
        if ("HAPPYBATH" in upper) or ("해피바스" in s_clean):
            return "해피바스"
        if ("VITALBEAUTIE" in upper) or ("바이탈뷰티" in s_clean):
            return "바이탈뷰티"
        if ("LONGTAKE" in upper) or ("롱테이크" in s_clean):
            return "롱테이크"

        # 4) fallback: cleaned string
        return s_clean
    def select_product(self, row: Dict[str, Any], topk: int = 3, results: Optional[List[str]] = None) -> Tuple[Optional[str], float]:
        """Compatibility wrapper.

        - 일부 코드(또는 과거 버전)에서 `select_product(row, topk=...)`를 호출하는 경우를 흡수한다.
        - `results`(후보 리스트)가 주어지면 그 후보 범위에서만 선택하고,
          주어지지 않으면 DF의 전체 상품명을 후보로 사용한다.
        """
        if self.df is None or not self.name_col or not self.brand_col:
            raise TypeError(
                "ProductSelector is not configured. Provide df/name_col/brand_col "
                "via constructor or call configure(df, name_col, brand_col) before select_product()."
            )

        if results is None:
            # 전체 후보
            results = [x for x in self.df[self.name_col].unique().tolist() if x is not None]

        # 기존 로직 재사용
        chosen_name, chosen_score = self.select_best_product(results=results, row=row)

        # `topk`는 select_best_product 내부에서 현재 고정값(3)을 사용 중이므로,
        # 호출 호환만 보장한다(추후 필요 시 select_best_product의 topk 파라미터화를 별도 작업으로).
        return chosen_name, chosen_score

    @staticmethod
    def _extract_persona_keywords(row: Any) -> List[str]:
        """Extract persona keywords for business rules (kept concise + stable)."""
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
                s = "" if v is None else str(v).strip()
                if not s:
                    continue
                for token in s.replace("/", ",").replace(";", ",").split(","):
                    t = token.strip()
                    if t:
                        persona_keywords.append(t)
        return persona_keywords

    def apply_brand_boost(
        self,
        row: Optional[Dict[str, Any]],
        persona_keywords: List[str],
        brand_name: str,
        original_score: float,
    ) -> float:
        """Contextual + Alignment logic.

        목적:
        - (1) TPO 불일치(바쁜 아침 vs 디바이스/하이 에포트) 같은 치명적 추천을 강하게 차단
        - (2) row['brand']가 주어진 경우, 해당 브랜드를 "우선 검토"하도록 가점(soft preference)

        주의:
        - 데이터 조작/강제 고정이 아니라, 설명 가능한 규칙 기반 보정만 수행
        """
        # --- normalize ---
        b_name = self._normalize_brand(brand_name)
        keywords_str = " ".join(persona_keywords or [])
        multiplier = 1.0

        # =========================================================
        # Logic 0. [Alignment Boost] persona에 지정된 브랜드 soft preference
        # =========================================================
        target_brand = None
        if isinstance(row, dict):
            rb = row.get("brand")
            if rb is not None:
                nb = self._normalize_brand(rb)
                if nb:
                    target_brand = nb

        # 타겟 브랜드면 강하게 우대(유사도가 약간 낮아도 경쟁 가능)
        if target_brand and (b_name == target_brand):
            multiplier *= 2.0

        # =========================================================
        # Logic 1. [TPO Kill Switch] 바쁜 아침(Busy) vs High Effort(디바이스/집중관리)
        # =========================================================
        is_busy = any(
            k in keywords_str
            for k in [
                "바쁜",
                "아침",
                "출근",
                "5분",
                "빠른",
                "간편",
                "귀차니즘",
                "올인원",
            ]
        )

        # 디바이스/집중관리 성격(시간/노력 요구)
        high_effort_brands = ["메이크온", "LG프라엘", "프라엘"]
        is_high_effort = (b_name in high_effort_brands) or ("MAKEON" in b_name.upper())

        # Busy context에서 High Effort면 사실상 탈락 수준으로 페널티
        if is_busy and is_high_effort:
            multiplier *= 0.1

        # =========================================================
        # Logic 2. [Derma & Safety] 민감성/장벽 -> 더마 우대, 고기능성 리스크 하향
        # =========================================================
        is_sensitive = any(
            k in keywords_str
            for k in [
                "민감",
                "트러블",
                "여드름",
                "홍조",
                "장벽",
                "뒤집어",
                "따가움",
                "진정",
            ]
        )

        derma_brands = ["에스트라", "일리윤", "순정", "프리메라"]
        active_brands = ["설화수", "헤라", "아이오페", "오딧세이"]

        if is_sensitive:
            if b_name in derma_brands:
                multiplier *= 1.3
            elif b_name in active_brands:
                multiplier *= 0.5

        # =========================================================
        # Logic 3. [Luxury vs Mass] 안티에이징 vs 가성비
        # =========================================================
        needs_antiaging = any(k in keywords_str for k in ["주름", "탄력", "노화", "리프팅", "기미", "안티에이징"])
        needs_cheap = any(k in keywords_str for k in ["가성비", "학생", "대학생", "저렴", "세일", "로드샵"])

        luxury_brands = ["설화수", "헤라", "아모레퍼시픽", "아이오페", "바이탈뷰티"]
        mass_brands = ["에뛰드", "이니스프리", "해피바스"]

        if needs_antiaging:
            if b_name in luxury_brands:
                multiplier *= 1.2
            elif b_name in mass_brands:
                multiplier *= 0.9

        if needs_cheap:
            if b_name in mass_brands:
                multiplier *= 1.2
            elif b_name in luxury_brands:
                multiplier *= 0.2

        # =========================================================
        # Logic 4. [Value Consumption] 비건/윤리
        # =========================================================
        is_eco = any(k in keywords_str for k in ["비건", "환경", "클린", "동물", "윤리"])
        eco_brands = ["프리메라", "롱테이크", "이니스프리"]

        if is_eco:
            if b_name in eco_brands:
                multiplier *= 1.2
            else:
                multiplier *= 0.9

        return float(original_score) * float(multiplier)

    def select_best_product(self, results, row) -> Tuple[Optional[str], float]:
        if self.df is None or not self.name_col or not self.brand_col:
            raise TypeError(
                "ProductSelector is not configured. Provide df/name_col/brand_col "
                "via constructor or call configure(df, name_col, brand_col) before select_best_product()."
            )

        # Persona keywords for business rules
        persona_keywords: List[str] = self._extract_persona_keywords(row)

        # Optional strict brand constraint: if persona specifies a brand,
        # only consider products from that brand. If this yields no candidates,
        # fall back to non-filtered selection.
        target_brand_norm: Optional[str] = None
        if isinstance(row, dict):
            rb = row.get("brand")
            nb = self._normalize_brand(rb)
            if nb:
                target_brand_norm = nb

        def _collect_candidates(brand_filter: Optional[str]) -> List[Tuple[str, float]]:
            collected: List[Tuple[str, float]] = []
            for name in results:
                sub_df = self.df[self.df[self.name_col] == name]
                if sub_df.empty:
                    continue

                # brand string (normalized for strict matching)
                b_raw_local = sub_df.iloc[0][self.brand_col]
                b_norm_local = self._normalize_brand(b_raw_local)

                # Hard filter (only when persona brand exists)
                if brand_filter and b_norm_local != brand_filter:
                    continue

                # precomputed similarity columns (0.0 ~ 1.0). If absent, treat as 0.
                sim_benefit = float(sub_df.iloc[0]["benefit_score"]) if "benefit_score" in sub_df.columns else 0.0
                sim_identity = float(sub_df.iloc[0]["identity_score"]) if "identity_score" in sub_df.columns else 0.0
                sim_emotion = float(sub_df.iloc[0]["emotion_score"]) if "emotion_score" in sub_df.columns else 0.0

                # Benefit 중심 가중치(0.6/0.3/0.1)
                final_score = (0.6 * sim_benefit) + (0.3 * sim_identity) + (0.1 * sim_emotion)

                persona_id_local = row.get("persona_id") if isinstance(row, dict) else None
                weight = PERSONA_BRAND_WEIGHT.get(persona_id_local, {}).get(b_norm_local, 1.0)
                weighted_score_local = final_score * weight

                # contextual/business logic
                weighted_score_local = self.apply_brand_boost(
                    row=row if isinstance(row, dict) else None,
                    persona_keywords=persona_keywords,
                    brand_name=str(b_raw_local) if b_raw_local is not None else "",
                    original_score=weighted_score_local,
                )

                collected.append((name, float(weighted_score_local)))
            return collected

        # First pass: enforce persona brand if provided
        candidates: List[Tuple[str, float]] = _collect_candidates(target_brand_norm)
        # Fallback: if persona brand exists but no products matched, drop the hard filter
        if target_brand_norm and not candidates:
            candidates = _collect_candidates(None)

        if not candidates:
            return None, -1.0

        # Top-K sampling for diversity (score-proportional)
        topk = 3  # Default Top-K value, can be parameterized if needed
        candidates.sort(key=lambda x: x[1], reverse=True)

        k = max(1, int(topk))
        final_candidates = candidates[:k]

        # Score-proportional sampling for diversity (no numpy dependency)
        import random

        scores = [c[1] for c in final_candidates]
        # shift to non-negative weights
        weights = [max(0.0, s) for s in scores]

        if sum(weights) <= 0.0:
            chosen = final_candidates[0]
        else:
            chosen = random.choices(final_candidates, weights=weights, k=1)[0]

        return chosen[0], float(chosen[1])