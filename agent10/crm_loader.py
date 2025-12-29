import pandas as pd
from pathlib import Path
import sys

class CRMLoader:
    def __init__(self, data_dir: Path = None):
        """
        data_dir: 외부에서 경로를 받아오지만, 경로 오류 방지를 위해 
                  내부에서 계산된 절대 경로(real_data_dir)를 우선 사용합니다.
        """
        # [경로 자동 보정]
        # 현재 파일(crm_loader.py)의 위치를 기준으로 data 폴더를 찾습니다.
        # agent10 폴더의 상위(parent)가 프로젝트 루트입니다.
        project_root = Path(__file__).resolve().parent.parent
        real_data_dir = project_root / "data"

        # 실제 경로를 사용하도록 설정
        self.data_dir = real_data_dir

        # 디버깅용 출력
        # print(f"[CRMLoader] Data path resolved to: {self.data_dir}")

    def load(self, persona_id, topk):
        # 1. 메인 데이터 로드
        file_path_base = self.data_dir / "persona_brand_tone_part_final.csv"
        if not file_path_base.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path_base}")
            
        base = pd.read_csv(file_path_base)

        # 2. 페르소나 메타 데이터 로드
        file_path_meta = self.data_dir / "persona_meta_v2.csv"
        if not file_path_meta.exists():
            print(f"[Warning] 메타 파일 없음: {file_path_meta}")
            # 메타 파일이 없으면 병합하지 않고 기본 데이터만 리턴하거나 빈 프레임 처리
            # 여기서는 에러 방지를 위해 base만 처리하도록 할 수 있으나, 
            # 원본 로직 유지를 위해 에러를 띄우는 게 낫습니다.
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path_meta}")

        persona = pd.read_csv(file_path_meta)

        # 3. 데이터 병합 및 필터링
        df = base.merge(persona, on="persona_id", how="left")
        
        # 해당 페르소나 필터링 및 점수 정렬
        df = df[df["persona_id"] == persona_id].sort_values("score", ascending=False)

        return df.head(topk).to_dict("records")

    def load_tone_profile_map(self):
        p = self.data_dir / "tone_profile_map.csv"
        if not p.exists():
            return {}
        df = pd.read_csv(p)
        return dict(zip(df.iloc[:, 0], df.iloc[:, 1]))