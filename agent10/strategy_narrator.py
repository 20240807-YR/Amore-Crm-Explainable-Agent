import json
import traceback

# [Import Fix] brand_rules 파일에서 함수를 명확하게 가져옵니다.
# (이 부분이 없으면 NameError가 발생합니다)
from brand_rules import build_brand_rule_block

class StrategyNarrator:
    def __init__(self, llm, tone_profile_map=None):
        """
        :param llm: OpenAI Client 객체 (generate 메서드에서 사용)
        :param tone_profile_map: 페르소나별 톤 앤 매너 키워드 맵
        """
        self.llm = llm
        self.tone_profile_map = tone_profile_map or {}

    def generate(self, row: dict, plan: dict, brand_rule: dict, repair_errors: list = None):
        """
        LLM을 사용하여 CRM 마케팅 메시지(Title + Body)를 생성합니다.
        기존의 딱딱한 템플릿 방식 대신, AI가 자연스럽게 작성하도록 유도합니다.
        """
        
        # 1. 페르소나 및 톤 정보 준비
        persona_id = row.get("persona_id", "Unknown")
        # 톤 프로필이 없으면 기본값 설정
        tone_keyword = self.tone_profile_map.get(persona_id, "친절하고 공감하는 뷰티 카운셀러 톤")
        
        # 2. 브랜드 규칙 블록 생성 (brand_rules.py의 함수 사용)
        rule_block = build_brand_rule_block(brand_rule)

        # 3. 상품 정보 포맷팅
        product_info = (
            f"- 상품명: {row.get('상품명', '')}\n"
            f"- URL: {row.get('URL', '')}\n"
            f"- 고객 피부고민: {row.get('skin_concern', '복합성')}\n"
            f"- 주요 성분/특징: {row.get('전성분', '')[:150]}..." # 너무 길면 자름
        )

        # 4. 전략(Plan) 정보를 문자열로 변환
        plan_str = json.dumps(plan, ensure_ascii=False, indent=2)
        
        # 5. 시스템 프롬프트 (페르소나 부여)
        system_prompt = (
            "당신은 아모레퍼시픽의 숙련된 '뷰티 카운셀러'입니다.\n"
            f"고객의 페르소나에 맞춰 '{tone_keyword}'으로 메시지를 작성하세요.\n\n"
            "[작성 지침]\n"
            "1. 말투: 기계적인 번역투나 딱딱한 문어체를 피하고, 옆에서 말해주듯 자연스러운 '해요체'를 사용하세요.\n"
            "2. 기호 금지: '유분↑', '수분→' 같은 특수기호를 절대 쓰지 말고 서술형으로 풀어쓰세요.\n"
            "3. 구조: 고객의 고민에 먼저 공감해주고, 자연스럽게 제품을 추천하며 해결책을 제시하세요.\n"
            "4. 길이: 모바일에서 읽기 편하게 300~350자 내외로 작성하세요.\n"
            "5. 필수: 반드시 아래 [Brand Rule]을 준수해야 합니다.\n\n"
            f"{rule_block}\n"
        )

        # 6. 사용자 프롬프트 (입력 데이터)
        user_prompt = (
            "아래 고객 정보와 마케팅 전략(Plan)을 바탕으로 매력적인 CRM 메시지를 작성해줘.\n\n"
            f"[상품 및 고객 정보]\n{product_info}\n\n"
            f"[전략 기획(Reasoning)]\n{plan_str}\n\n"
        )

        # 7. 재수정(Self-Correction) 요청 처리
        # 검증기(Verifier)에서 에러가 발견되어 재요청이 들어온 경우
        if repair_errors:
            user_prompt += (
                f"\n[🚨 수정 요청]\n"
                f"이전 생성물에서 다음 문제가 발견되었습니다:\n{repair_errors}\n"
                "위 지적사항을 반영하여 메시지를 다시 작성해주세요.\n"
            )

        # 8. 출력 형식 지정
        user_prompt += (
            "\n[출력 형식]\n"
            "TITLE: (고객의 클릭을 유도하는 매력적인 제목)\n"
            "BODY: (본문 내용, URL은 맨 마지막에 원본 그대로 입력)\n"
            "주의: URL을 [링크](주소) 형태로 변환하지 마세요. http://... 주소만 남기세요.\n"
            "형식을 꼭 지켜주세요."
        )

        # 9. LLM 호출
        try:
            # llm 객체가 chat 메서드를 가지고 있다고 가정 (openai_client.py)
            response = self.llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ])
            return response.strip()
            
        except Exception as e:
            print(f"[StrategyNarrator] LLM Generation Error: {e}")
            traceback.print_exc()
            # 에러 발생 시 비상용 메시지 리턴
            return (
                "TITLE: 고객님을 위한 맞춤 추천\n"
                "BODY: 죄송합니다. 메시지 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
            )