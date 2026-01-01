# agent10/strategy_narrator.py
import re
from typing import Any, Dict, List, Optional, Tuple


class StrategyNarrator:
    """
    - plan(message_outline) 없으면 generate 실행 금지
    - BODY는 1:1:1:1 슬롯(4줄) 강제: 라이프스타일 → 제품 → 라이프스타일(루틴) → 추가 메시지(구매 텀/채널/혜택)
    - BODY 300~350자, URL 정확히 1회(마지막), 마크다운 링크 금지
    - 메타/기획/전략 표현 금지
    """

    # ✅ controller.py에서 StrategyNarrator(llm, tone_profile_map=tone_map)로 호출하므로
    # ✅ 여기서 tone_profile_map을 "받기만" 해서 TypeError를 막는다(사용은 안 함).
    def __init__(
        self,
        llm_client,
        pad_pool: Optional[List[str]] = None,
        tone_profile_map: Optional[Dict[str, Any]] = None,  # <-- 추가(호환용)
        **kwargs,  # <-- 혹시 다른 키워드가 와도 터지지 않게(호환용)
    ):
        self.llm = llm_client
        self.tone_profile_map = tone_profile_map or {}  # 사용 안 해도 저장만
        self.pad_pool = pad_pool or [
            "오늘 컨디션에 맞춰 가볍게 얹기 좋아요.",
            "부담 없이 매일 이어가기 편해요.",
            "끈적임이 덜해 손이 자주 가요.",
            "바쁠수록 짧게 정리되는 루틴이 편하죠.",
            "가볍게 마무리돼 다음 단계가 수월해요.",
        ]

        # meta/기획/CTA 금지(강제)
        self.meta_ban_phrases = [
            "브랜드 톤을 유지하며",
            "브랜드 톤을 살려",
            "브랜드 톤을 살리",
            "설계된 제품",
            "기획된",
            "전략적으로",
            "톤을 반영하여",
            "브랜드 아이덴티티",
            "클릭",
            "구매하기",
            "더 알아보려면",
            "더 알아보기",
            "자세히 보기",
            # 문제로 지적된 어색한 종결문(직접 차단)
            "지속 가능성 측면에서도 부담 없이 이어갈 수",
            "이 과정에서 루틴 내 위치, 지속 가능성 측면에서도",
        ]
        self.meta_ban_regex = [
            r"브랜드\s*톤(을|이)?\s*(유지|살리|살려|반영)",
            r"(클릭|구매\s*하기|구매하기|더\s*알아\s*보(려면|기)|자세히\s*보(기|려면))",
            r"(전략적|기획된|설계된)\s*",
            r"지속\s*가능성\s*측면",
        ]

    # -------------------------
    # utils
    # -------------------------
    def _s(self, v: Any) -> str:
        return "" if v is None else str(v).strip()

    def _get_url(self, row: Dict[str, Any]) -> str:
        for k in ["url", "URL", "product_url", "productURL", "상품URL", "상품_url", "link", "링크"]:
            v = self._s(row.get(k))
            if v and v.lower() != "nan":
                return v
        return ""

    def _strip_markdown_link(self, text: str) -> str:
        # [text](http...) 형태를 plain text로 치환(금지이므로 제거)
        return re.sub(r"\[([^\]]+)\]\(https?://[^\)]+\)", r"\1", text)

    def _contains_banned(self, text: str) -> bool:
        if not text:
            return False
        for p in self.meta_ban_phrases:
            if p and p in text:
                return True
        for rx in self.meta_ban_regex:
            if re.search(rx, text):
                return True
        return False

    def _hard_clean(self, text: str) -> str:
        t = self._s(text)
        t = self._strip_markdown_link(t)
        # URL 여러 개면 일단 전부 제거(나중에 딱 1개를 마지막에 붙임)
        t = re.sub(r"https?://[^\s]+", "", t, flags=re.IGNORECASE)
        # 공백 정리
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _ensure_title_len(self, title: str) -> str:
        title = self._s(title)
        if len(title) <= 40:
            return title
        # 40자 초과면 뒤를 잘라냄(이모지 포함 그대로 길이 기준)
        return title[:40].rstrip()

    def _split_4lines(self, body: str) -> List[str]:
        lines = [ln.strip() for ln in self._s(body).split("\n") if ln.strip()]
        if len(lines) >= 4:
            return lines[:4]
        # 문장부호 기반 분해
        parts = re.split(r"[.!?…~]+", self._s(body))
        parts = [p.strip() for p in parts if p and p.strip()]
        if len(parts) >= 4:
            return parts[:4]
        # 부족하면 통째로 1줄로 두고 나머지는 빈칸으로 채움
        while len(lines) < 4:
            lines.append("")
        if not lines[0]:
            lines[0] = self._s(body)
        return lines[:4]

    def _join_4lines(self, lines: List[str]) -> str:
        lines = [self._s(x) for x in lines[:4]]
        return "\n".join([x for x in lines if x])

    def _fit_len_300_350(self, lines: List[str], url: str) -> Tuple[List[str], str]:
        """
        - URL은 마지막 라인의 끝에 1회만 붙임
        - BODY(줄바꿈 포함 전체 문자열) 길이를 300~350에 맞춤
        """
        url = self._s(url)
        lines = [self._hard_clean(x) for x in lines[:4]]

        # (1) slot4에 URL 붙이기 전 길이 기반 보정
        def compose(with_url: bool) -> str:
            b = self._join_4lines(lines)
            if with_url and url:
                # URL은 마지막에 공백 하나 두고 붙임
                b = b.rstrip()
                b = re.sub(r"[\s\)\]\}.,!?:;…~]+$", "", b)  # 끝 구두점 제거
                b = (b + " " + url).strip()
            return b

        # (2) 최소 길이 맞추기: slot4에 패딩 문장 추가(메타 금지 회피)
        _ = compose(with_url=False)
        # URL이 없으면 여기서 길이 맞추더라도 verifier가 url_missing을 낼 수 있음(그건 데이터 문제)
        while len(compose(with_url=True)) < 300 and url:
            added = ""
            for cand in self.pad_pool:
                if cand and not self._contains_banned(cand):
                    added = cand
                    break
            if not added:
                break
            # slot4에 자연스럽게 추가
            if lines[3]:
                if not lines[3].endswith(("요", "죠", "해요", "이에요", "예요", "네요", "어요", "아요", ".", "!", "?", "…", "~")):
                    lines[3] = lines[3].rstrip() + "."
                lines[3] = (lines[3].rstrip() + " " + added).strip()
            else:
                lines[3] = added

        # (3) 최대 길이 맞추기: slot4부터 줄임(필수 키워드 훼손 최소화)
        def trim_one_step(s: str) -> str:
            s = self._s(s)
            if not s:
                return s
            # 뒤에서 한 덩어리(쉼표/마침표/스페이스 기준) 잘라냄
            s2 = re.sub(r"[\s\)\]\}.,!?:;…~]+$", "", s)
            # 마지막 구를 제거
            if " " in s2:
                return s2.rsplit(" ", 1)[0].strip()
            return s2[: max(0, len(s2) - 1)].strip()

        # URL 포함 최종 기준으로 350 초과면 줄이기
        if url:
            while len(compose(with_url=True)) > 350:
                before = lines[3]
                lines[3] = trim_one_step(lines[3])
                if lines[3] == before:
                    break
                # 너무 짧아져 slot4가 붕괴하면 slot3도 조금 줄임
                if len(lines[3]) < 20:
                    lines[2] = trim_one_step(lines[2])

        # (4) 최종 반환: URL을 마지막에 1회만 붙임
        final_body = compose(with_url=True) if url else self._join_4lines(lines)
        # 혹시 URL이 중간에 섞였으면 제거 후 다시 붙임
        if url:
            final_body = re.sub(r"https?://[^\s]+", "", final_body, flags=re.IGNORECASE).strip()
            final_body = re.sub(r"\s+", " ", final_body).strip()
            # 4줄 유지(줄바꿈 복원)
            # - 줄바꿈은 verifier 슬롯 분해에 유리하니, 여기서는 기존 4줄을 유지하고 마지막에 URL만 붙임
            lines2 = [self._hard_clean(x) for x in lines[:4]]
            final_body = self._join_4lines(lines2).rstrip()
            final_body = re.sub(r"[\s\)\]\}.,!?:;…~]+$", "", final_body)
            final_body = (final_body + " " + url).strip()

        return lines, final_body

    # -------------------------
    # prompt
    # -------------------------
    def _build_prompt(
        self,
        row: Dict[str, Any],
        plan: Dict[str, Any],
        brand_must_include: Optional[List[str]] = None,
    ) -> Tuple[str, str]:
        persona_name = self._s(row.get("persona_name"))
        brand = self._s(row.get("brand_name_slot")) or self._s(row.get("brand"))
        prod = self._s(row.get("상품명"))
        lifestyle = self._s(row.get("lifestyle"))
        skin_concern = self._s(row.get("skin_concern"))
        allergy = self._s(row.get("allergy_sensitivity"))
        texture = self._s(row.get("texture_preference"))
        finish = self._s(row.get("finish_preference"))
        scent = self._s(row.get("scent_preference"))
        routine_step = self._s(row.get("routine_step_count"))
        time_of_use = self._s(row.get("time_of_use"))
        seasonality = self._s(row.get("seasonality"))
        env = self._s(row.get("environment_context"))
        shopping_channel = self._s(row.get("shopping_channel"))
        repurchase = self._s(row.get("repurchase_tendency"))
        cta_style = self._s(row.get("cta_style"))
        ethical = self._s(row.get("ethical_preference"))
        avoid_list = self._s(row.get("ingredient_avoid_list"))

        outline = plan.get("message_outline") if isinstance(plan, dict) else None
        outline = outline if isinstance(outline, list) else []

        musts = brand_must_include or []
        musts_str = ", ".join([m for m in musts if m])

        # ✅ 예시 2종 반영 (둘 다 "참고"만, 그대로 복붙 금지)
        # - 두 번째 예시는 네가 준 원문을 그대로 넣되,
        #   시스템 규칙에서 '지속 가능성 측면' 말투는 금지이므로 "금지 예시"로 명시해 둠.
        fewshot = (
            "예시(형식/톤 참고, 그대로 복붙 금지):\n"
            "TITLE: ✨🌟출근 전 간편 피부 루틴! 프리메라와 함께💧\n"
            "BODY: 출근 전 바쁜 아침, 사무실 에어컨과 마스크로 속건조·피지·모공이 신경 쓰이기 쉬워요.\n"
            "프리메라 NEW 나이아시카 수딩 글로우 워터리 크림30ml는 워터리하게 스며들어 가볍게 수분을 채우는 느낌이 좋아요.\n"
            "세안 후 토너로 정리한 다음 한 번만 쓱, 아침/저녁 3~4단계 루틴에 얹어도 부담이 덜해요.\n"
            "자사몰/앱에서 혜택을 챙겨 담기 좋고, 루틴 내 위치가 또렷한 데다 지속 가능성도 같이 챙겨서 꾸준히 이어가기 편해요:) https://example.com\n\n"
            "금지 예시(이 표현/리듬으로 쓰지 말 것):\n"
            "TITLE: ✨ 🌟출근 전 간편 피부 루틴! 프리메라와 함께해요💧\n"
            "BODY: 출근 전 바쁜 아침, 사무실 에어컨과 마스크로 속건조, 피지, 모공 문제에 시달리기 쉬워요. "
            "이런 일상 속에서 프리메라의 NEW 나이아시카 수딩 글로우 워터리 크림 30ml를 활용해보면 어떨까요? "
            "가벼운 사용감으로 부담 없이 바를 수 있어요. 세안 후 토너로 정리한 피부에 쓱 바르면 덜 끈적하게 수분이 채워지죠. "
            "특히 지속 가능한 원료로 만들어져 환경까지 생각한 제품이라 더욱 안심이에요. 정돈된 피부로 자신감 있게 하루를 시작해보세요!. "
            "프리메라와 함께라면 루틴 내 위치, 지속 가능성 측면에서도 부담 없이 이어갈 수 있을 거예요:)\n"
        )

        system = (
            "너는 CRM 추천 메시지를 쓰는 카피라이터다. "
            "출력은 반드시 2줄만:\n"
            "1) TITLE: ... (40자 이내)\n"
            "2) BODY: ... (반드시 4줄/4슬롯, 각 줄은 문장 1~2개)\n\n"
            "규칙(강제):\n"
            "- BODY는 4줄(슬롯 1:1:1:1)로 줄바꿈 포함해 작성\n"
            "  1) 라이프스타일/환경 맥락\n"
            "  2) 피부 고민 ↔ 제품 연결(제품명 포함)\n"
            "  3) 루틴/시간대/사용 흐름(아침/저녁/루틴/매일/관리 등 포함)\n"
            "  4) 추가 메시지(구매 텀 완곡 + 채널/혜택 마무리)\n"
            "- BODY 총 길이 300~350자\n"
            "- URL은 정확히 1개만, BODY의 마지막에 1회만 붙이기(마크다운 링크 금지)\n"
            "- 금지: 메타/기획/전략 표현, '클릭/구매하기/더 알아보려면' 류\n"
            "- 특히 '지속 가능성 측면' 같은 말투/문장 그대로 사용 금지(자연스럽게만)\n"
        )

        user = (
            f"{fewshot}\n"
            "아래 정보를 반영해서 새 메시지를 작성:\n"
            f"- persona_name: {persona_name}\n"
            f"- brand: {brand}\n"
            f"- product_name: {prod}\n"
            f"- lifestyle: {lifestyle}\n"
            f"- skin_concern: {skin_concern}\n"
            f"- allergy_sensitivity: {allergy}\n"
            f"- texture_preference: {texture}\n"
            f"- finish_preference: {finish}\n"
            f"- scent_preference: {scent}\n"
            f"- routine_step_count: {routine_step}\n"
            f"- time_of_use: {time_of_use}\n"
            f"- seasonality: {seasonality}\n"
            f"- environment_context: {env}\n"
            f"- shopping_channel: {shopping_channel}\n"
            f"- repurchase_tendency: {repurchase}\n"
            f"- cta_style: {cta_style}\n"
            f"- ethical_preference: {ethical}\n"
            f"- ingredient_avoid_list: {avoid_list}\n"
            f"- message_outline(반드시 4슬롯에 대응): {outline}\n"
            f"- brand_must_include(가능하면 자연스럽게 포함): {musts_str}\n\n"
            "출력 형식 엄수:\n"
            "TITLE: ...\n"
            "BODY: (4줄)\n"
        )

        return system, user

    # -------------------------
    # main
    # -------------------------
    def generate(
        self,
        row: Dict[str, Any],
        plan: Dict[str, Any],
        brand_must_include: Optional[List[str]] = None,
        temperature: float = 0.7,
        max_retries: int = 2,
        **kwargs,  # controller 호환용 (brand_rule 등 무시)
    ) -> Dict[str, str]:
        """
        반환:
          {
            "title_line": "TITLE: ...",
            "body_line":  "BODY: ...",
            "title": "...",
            "body":  "...",
          }
        """
        # plan(message_outline) 없으면 실행 금지
        if not isinstance(plan, dict) or not isinstance(plan.get("message_outline"), list) or len(plan["message_outline"]) < 4:
            raise ValueError("StrategyNarrator.generate blocked: plan.message_outline missing")

        url = self._get_url(row)

        system, user = self._build_prompt(row=row, plan=plan, brand_must_include=brand_must_include)

        last_err = None
        for _ in range(max_retries + 1):
            # llm_client는 messages 기반/문자열 기반 모두 대응
            raw = None
            try:
                # 다양한 llm_client 인터페이스 호환: generate / invoke / __call__
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]

                if hasattr(self.llm, "generate") and callable(getattr(self.llm, "generate")):
                    # 1) messages 인자를 받는 경우
                    try:
                        raw = self.llm.generate(messages=messages, temperature=temperature)
                    except TypeError:
                        # 2) (system, user) 시그니처인 경우
                        raw = self.llm.generate(system, user)

                elif hasattr(self.llm, "invoke") and callable(getattr(self.llm, "invoke")):
                    # LangChain 류: invoke(input)
                    try:
                        raw = self.llm.invoke(messages)
                    except TypeError:
                        raw = self.llm.invoke({"messages": messages, "temperature": temperature})

                elif callable(self.llm):
                    # __call__ 지원: messages 또는 (system, user)
                    try:
                        raw = self.llm(messages=messages, temperature=temperature)
                    except TypeError:
                        try:
                            raw = self.llm(messages)
                        except TypeError:
                            raw = self.llm(system, user)

                else:
                    # Fallback: OpenAIChatCompletionClient 내부 client 사용
                    if hasattr(self.llm, "client") and hasattr(self.llm.client, "chat"):
                        raw = self.llm.client.chat.completions.create(
                            model=getattr(self.llm, "model", "gpt-4o-mini"),
                            messages=messages,
                            temperature=temperature,
                        ).choices[0].message.content
                    else:
                        raise AttributeError("llm_client has no usable interface")
            except Exception as e:
                last_err = e
                continue

            text = self._s(raw)
            # 방어: 혹시 딕셔너리/리스트로 오면 문자열로
            if not isinstance(raw, str):
                text = self._s(raw)

            # TITLE/BODY 추출
            title_match = re.search(r"^TITLE:\s*(.+)$", text, flags=re.MULTILINE)
            body_match = re.search(r"^BODY:\s*(.+)$", text, flags=re.MULTILINE | re.DOTALL)

            title = title_match.group(1).strip() if title_match else ""
            body = body_match.group(1).strip() if body_match else ""

            # 클린 + 4슬롯 강제 + URL 마지막/1회 강제
            title = self._ensure_title_len(self._hard_clean(title))
            body = self._hard_clean(body)

            lines = self._split_4lines(body)
            # 4줄이 안 나오면 빈 줄 채워서라도 4슬롯 형태 유지
            while len(lines) < 4:
                lines.append("")

            # brand_must_include는 "가능하면"이지만, 어색한 종결문은 차단
            # (루틴 내 위치 / 지속 가능성 등의 단어는 자연스럽게 흩뿌리도록 유도만 하고 강제 문구는 막음)
            for i in range(4):
                if self._contains_banned(lines[i]):
                    # 해당 라인은 강제 정리(문구 제거)
                    for p in self.meta_ban_phrases:
                        if p:
                            lines[i] = lines[i].replace(p, "")
                    for rx in self.meta_ban_regex:
                        lines[i] = re.sub(rx, "", lines[i])
                    lines[i] = re.sub(r"\s+", " ", lines[i]).strip()

            lines, final_body = self._fit_len_300_350(lines, url=url)

            # 최종 금지어 재검사(여기서 걸리면 재시도)
            if self._contains_banned(final_body):
                last_err = ValueError("banned_phrase_detected")
                continue

            # TITLE/BODY 라인 포맷으로 반환
            title_line = f"TITLE: {title}".strip()
            body_line = f"BODY: {final_body}".strip()

            return {
                "title_line": title_line,
                "body_line": body_line,
                "title": title,
                "body": final_body,
            }

        if last_err:
            raise last_err
        raise RuntimeError("StrategyNarrator.generate failed")