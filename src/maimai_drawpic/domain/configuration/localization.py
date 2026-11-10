"""插件配置 WebUI Schema 的多语言元数据。"""

from collections.abc import Iterable
from maibot_sdk import PluginConfigBase
from typing import Dict, Tuple, Type


_LOCALES = ("en_US", "ja_JP", "ko_KR")

_SECTION_TEXTS: Dict[str, Tuple[Tuple[str, str, str], Tuple[str, str, str]]] = {
    "MiniMaxModelConfig": (("MiniMax Settings", "MiniMax 設定", "MiniMax 설정"), ("Official MiniMax image models.", "MiniMax 公式画像モデルの設定。", "MiniMax 공식 이미지 모델 설정.")),
    "AgnesModelConfig": (
        ("Agnes Settings", "Agnes 設定", "Agnes 설정"),
        ("Agnes image generation and editing.", "Agnes の画像生成・編集設定です。", "Agnes 이미지 생성 및 편집 설정입니다."),
    ),
    "PluginSectionConfig": (
        ("Plugin Settings", "プラグイン設定", "플러그인 설정"),
        ("Basic plugin settings.", "プラグインの基本設定です。", "플러그인의 기본 설정입니다."),
    ),
    "GeneralConfig": (
        ("General Settings", "一般設定", "일반 설정"),
        (
            "General drawing behavior and permissions.",
            "描画動作と権限の一般設定です。",
            "그리기 동작과 권한의 일반 설정입니다.",
        ),
    ),
    "StylePresetConfig": (
        ("Style Preset", "スタイルプリセット", "스타일 프리셋"),
        ("A reusable drawing style preset.", "再利用できる描画スタイルです。", "재사용 가능한 그리기 스타일입니다."),
    ),
    "StyleConfig": (
        ("Drawing Styles", "描画スタイル", "그리기 스타일"),
        (
            "Prompt templates shared by all providers.",
            "全プロバイダー共通のプロンプトテンプレートです。",
            "모든 제공자가 공유하는 프롬프트 템플릿입니다.",
        ),
    ),
    "ProxyConfig": (
        ("Proxy Settings", "プロキシ設定", "프록시 설정"),
        (
            "Global proxy settings for image providers.",
            "画像プロバイダー用の共通プロキシ設定です。",
            "이미지 제공자용 전역 프록시 설정입니다.",
        ),
    ),
    "OpenAICompatibleInstanceConfig": (
        ("OpenAI-Compatible Instance", "OpenAI 互換インスタンス", "OpenAI 호환 인스턴스"),
        (
            "Settings for one OpenAI-compatible endpoint.",
            "OpenAI 互換エンドポイントの設定です。",
            "OpenAI 호환 엔드포인트 설정입니다.",
        ),
    ),
    "OpenAIModelConfig": (
        ("OpenAI Settings", "OpenAI 設定", "OpenAI 설정"),
        ("OpenAI image model settings.", "OpenAI 画像モデルの設定です。", "OpenAI 이미지 모델 설정입니다."),
    ),
    "GoogleModelConfig": (
        ("Google Settings", "Google 設定", "Google 설정"),
        (
            "Google Gemini and Imagen model settings.",
            "Google Gemini と Imagen の設定です。",
            "Google Gemini 및 Imagen 모델 설정입니다.",
        ),
    ),
    "ZhipuModelConfig": (
        ("Zhipu Settings", "智譜設定", "Zhipu 설정"),
        (
            "Zhipu GLM-Image and CogView settings.",
            "智譜 GLM-Image と CogView の設定です。",
            "Zhipu GLM-Image 및 CogView 설정입니다.",
        ),
    ),
    "AliyunModelConfig": (
        ("Alibaba Cloud Model Studio", "Alibaba Cloud Model Studio", "Alibaba Cloud Model Studio"),
        (
            "Alibaba Cloud image model settings.",
            "Alibaba Cloud 画像モデルの設定です。",
            "Alibaba Cloud 이미지 모델 설정입니다.",
        ),
    ),
    "VolcengineModelConfig": (
        ("Volcengine Settings", "Volcengine 設定", "Volcengine 설정"),
        (
            "Volcengine Ark image model settings.",
            "Volcengine Ark 画像モデルの設定です。",
            "Volcengine Ark 이미지 모델 설정입니다.",
        ),
    ),
    "SiliconFlowModelConfig": (
        ("SiliconFlow Settings", "SiliconFlow 設定", "SiliconFlow 설정"),
        (
            "SiliconFlow image model settings.",
            "SiliconFlow 画像モデルの設定です。",
            "SiliconFlow 이미지 모델 설정입니다.",
        ),
    ),
    "NovelAIModelConfig": (
        ("NovelAI / NovelAPI Settings", "NovelAI / NovelAPI 設定", "NovelAI / NovelAPI 설정"),
        (
            "NovelAI and NovelAPI image model settings.",
            "NovelAI と NovelAPI の設定です。",
            "NovelAI 및 NovelAPI 이미지 모델 설정입니다.",
        ),
    ),
    "ComfyUIModelConfig": (
        ("ComfyUI Settings", "ComfyUI 設定", "ComfyUI 설정"),
        (
            "Local ComfyUI workflow settings.",
            "ローカル ComfyUI ワークフローの設定です。",
            "로컬 ComfyUI 워크플로 설정입니다.",
        ),
    ),
    "PromptModerationConfig": (
        ("Prompt Review", "プロンプト審査", "프롬프트 검토"),
        ("Prompt review settings.", "プロンプト審査の設定です。", "프롬프트 검토 설정입니다."),
    ),
    "ImageModerationConfig": (
        ("Generated Image Review", "生成画像の審査", "생성 이미지 검토"),
        ("Generated image review settings.", "生成画像を審査する設定です。", "생성 이미지를 검토하는 설정입니다."),
    ),
}

_FIELD_LABELS: Dict[str, Tuple[str, str, str]] = {
    "integration_api_enabled": ("Plugin Integration API", "プラグイン連携 API", "플러그인 연동 API"),
    "group_access_mode": ("Group List Mode", "グループ一覧モード", "그룹 목록 모드"),
    "group_access_ids": ("Group Access List", "グループアクセス一覧", "그룹 접근 목록"),
    "private_access_mode": ("Private Chat List Mode", "個人チャット一覧モード", "개인 대화 목록 모드"),
    "private_access_ids": ("Private Chat Access List", "個人チャットアクセス一覧", "개인 대화 접근 목록"),
    "prompt_review_retry_count": ("Prompt Review Retries", "プロンプト審査の再試行回数", "프롬프트 검토 재시도 횟수"),
    "image_review_retry_count": ("Image Review Retries", "画像審査の再試行回数", "이미지 검토 재시도 횟수"),
    "prompt_review_model": ("Prompt Review Model", "プロンプト審査モデル", "프롬프트 검토 모델"),
    "image_review_model": ("Image Review Model", "画像審査モデル", "이미지 검토 모델"),
    "prompt_review_timeout_seconds": ("Prompt Review Wait (seconds)", "プロンプト審査の待機時間（秒）", "프롬프트 검토 대기 시간(초)"),
    "image_review_timeout_seconds": ("Image Review Wait (seconds)", "画像審査の待機時間（秒）", "이미지 검토 대기 시간(초)"),
    "skip_image_url_ip_check": (
        "Skip Image URL IP Checks", "画像 URL の IP 検証を省略", "이미지 URL IP 검사 건너뛰기"
    ),
    "ratio": ("Aspect Ratio", "アスペクト比", "화면 비율"),
    "image_cache_max_mb": ("Image Cache Limit (MB)", "画像キャッシュ上限（MB）", "이미지 캐시 한도(MB)"),
    "log_max_mb": ("Total Log Limit (MB)", "ログ合計上限（MB）", "전체 로그 한도(MB)"),
    "upload_cache_max_mb": ("Upload Cache Limit (MB)", "アップロードキャッシュ上限（MB）", "업로드 캐시 한도(MB)"),
    "add_watermark": ("Add Watermark", "ウォーターマークを追加", "워터마크 추가"),
    "admin_user_ids": ("Administrators", "管理者一覧", "관리자 목록"),
    "api_key": ("API Key", "API キー", "API 키"),
    "aspect_ratio": ("Aspect Ratio", "アスペクト比", "화면 비율"),
    "async_poll_interval_seconds": ("Async Poll Interval", "非同期ポーリング間隔", "비동기 폴링 간격"),
    "background": ("Background", "背景", "배경"),
    "base_url": ("Base URL", "ベース URL", "기본 URL"),
    "cfg": ("Qwen Image CFG", "Qwen Image CFG", "Qwen Image CFG"),
    "batch_size": ("Batch Size", "バッチサイズ", "배치 크기"),
    "bypass_china_providers": (
        "Bypass Proxy for China Providers",
        "中国プロバイダーはプロキシを回避",
        "중국 제공자 프록시 우회",
    ),
    "command_reply_mode": ("Command Reply Mode", "コマンド応答モード", "명령 응답 모드"),
    "sync_generated_images_to_history": (
        "Sync Generated Images to Chat History", "生成画像を会話履歴に同期", "생성 이미지를 대화 기록에 동기화",
    ),
    "config_version": ("Configuration Version", "設定バージョン", "설정 버전"),
    "custom_models": ("Custom Models", "カスタムモデル", "사용자 지정 모델"),
    "default_artist_tags": ("Default Artist Tags", "既定のアーティストタグ", "기본 아티스트 태그"),
    "default_mode": ("Default Mode", "既定モード", "기본 모드"),
    "default_model": ("Default Model", "既定モデル", "기본 모델"),
    "default_openai_compatibility_mode": (
        "Default OpenAI Compatibility Mode",
        "既定の OpenAI 互換モード",
        "기본 OpenAI 호환 모드",
    ),
    "default_size": ("Default Resolution", "既定の解像度", "기본 해상도"),
    "default_style": ("Default Style", "既定スタイル", "기본 스타일"),
    "description": ("Description", "説明", "설명"),
    "enabled": ("Enabled", "有効", "활성화"),
    "extra_parameters": ("Extra Parameters", "追加パラメータ", "추가 매개변수"),
    "failure_reason_enabled": ("Include Failure Reason", "失敗理由を表示", "실패 원인 표시"),
    "fallback_model": ("Fallback Model", "フォールバックモデル", "대체 모델"),
    "fallback_models": ("Ordered Fallback Models", "代替モデルの優先順位", "대체 모델 우선순위"),
    "request_retry_count": ("Maximum Retries per Model", "モデルごとの最大再試行回数", "모델별 최대 재시도 횟수"),
    "group_default_quota": ("Default Group Quota", "グループ既定クォータ", "그룹 기본 할당량"),
    "group_quota_enabled": ("Enable Group Quota", "グループクォータを有効化", "그룹 할당량 활성화"),
    "group_quota_period": ("Group Quota Period", "グループクォータ期間", "그룹 할당량 기간"),
    "guidance_scale": ("Guidance Scale", "ガイダンス強度", "가이던스 강도"),
    "height": ("Height", "高さ", "높이"),
    "host": ("Proxy Host", "プロキシホスト", "프록시 호스트"),
    "i2i_image_node_id": ("Image-to-Image Source Node ID", "画像変換の元画像ノード ID", "이미지 변환 원본 노드 ID"),
    "i2i_models": ("Image-to-Image Models", "画像変換モデル", "이미지 변환 모델"),
    "i2i_negative_prompt": (
        "Image-to-Image Negative Prompt",
        "画像変換のネガティブプロンプト",
        "이미지 변환 네거티브 프롬프트",
    ),
    "i2i_negative_prompt_node_id": (
        "Image-to-Image Negative Prompt Node ID",
        "画像変換ネガティブノード ID",
        "이미지 변환 네거티브 노드 ID",
    ),
    "i2i_positive_prompt_node_id": (
        "Image-to-Image Positive Prompt Node ID",
        "画像変換ポジティブノード ID",
        "이미지 변환 포지티브 노드 ID",
    ),
    "i2i_prompt_mode": ("Image-to-Image Prompt Mode", "画像変換プロンプトモード", "이미지 변환 프롬프트 모드"),
    "i2i_prompt_node_id": (
        "Image-to-Image Prompt Node ID",
        "画像変換プロンプトノード ID",
        "이미지 변환 프롬프트 노드 ID",
    ),
    "i2i_seed_node_id": ("Image-to-Image Seed Node ID", "画像変換シードノード ID", "이미지 변환 시드 노드 ID"),
    "i2i_workflow_path": ("Image-to-Image Workflow JSON", "画像変換ワークフロー JSON", "이미지 변환 워크플로 JSON"),
    "image_edit_unsupported_models": (
        "Models Without Image Editing",
        "画像編集非対応モデル",
        "이미지 편집 미지원 모델",
    ),
    "image_input_mode": ("Source Image Input Mode", "元画像入力モード", "원본 이미지 입력 모드"),
    "image_input_name": ("Source Image Input Field", "元画像入力フィールド", "원본 이미지 입력 필드"),
    "image_review_enabled": ("Enable Generated Image Review", "生成画像の審査を有効化", "생성 이미지 검토 활성화"),
    "image_review_prompt": ("Generated Image Review Template", "生成画像審査テンプレート", "생성 이미지 검토 템플릿"),
    "image_size": ("Image Size", "画像サイズ", "이미지 크기"),
    "img2img_noise": ("Image-to-Image Noise", "画像変換ノイズ", "이미지 변환 노이즈"),
    "img2img_strength": ("Image-to-Image Strength", "画像変換強度", "이미지 변환 강도"),
    "instances": ("OpenAI-Compatible Instances", "OpenAI 互換インスタンス", "OpenAI 호환 인스턴스"),
    "kling_aspect_ratio": ("Kling Aspect Ratio", "Kling アスペクト比", "Kling 화면 비율"),
    "kling_extra_parameters": ("Kling Extra Parameters", "Kling 追加パラメータ", "Kling 추가 매개변수"),
    "kling_resolution": ("Kling Resolution", "Kling 解像度", "Kling 해상도"),
    "kling_result_type": ("Kling Omni Result Mode", "Kling Omni 結果モード", "Kling Omni 결과 모드"),
    "kling_series_amount": ("Kling Omni Series Count", "Kling Omni シリーズ枚数", "Kling Omni 시리즈 수"),
    "layer_decomposition": ("Layer Decomposition", "レイヤー分解", "레이어 분해"),
    "max_images": ("Maximum Images", "最大画像数", "최대 이미지 수"),
    "model_endpoint_overrides": (
        "Per-Model Endpoint Overrides",
        "モデル別エンドポイント上書き",
        "모델별 엔드포인트 재정의",
    ),
    "model_size_overrides": ("Per-Model Resolution Overrides", "モデル別解像度上書き", "모델별 해상도 재정의"),
    "models": ("Models", "モデル一覧", "모델 목록"),
    "moderation": ("Moderation Level", "モデレーション強度", "검토 강도"),
    "name": ("Name", "名前", "이름"),
    "negative_prompt": ("Default Negative Prompt (Optional)", "既定のネガティブプロンプト（任意）", "기본 네거티브 프롬프트(선택 사항)"),
    "negative_prompt_enabled": ("Enable Negative Prompts", "ネガティブプロンプトを有効化", "네거티브 프롬프트 활성화"),
    "negative_prompt_template": (
        "Negative Prompt Template",
        "ネガティブプロンプトテンプレート",
        "네거티브 프롬프트 템플릿",
    ),
    "noise_schedule": ("Noise Schedule", "ノイズスケジュール", "노이즈 스케줄"),
    "num_inference_steps": ("Inference Steps", "推論ステップ数", "추론 단계"),
    "number_of_images": ("Number of Images", "生成画像数", "생성 이미지 수"),
    "output_format": ("Output Format", "出力形式", "출력 형식"),
    "output_mime_type": ("Output MIME Type", "出力 MIME タイプ", "출력 MIME 형식"),
    "optimize_prompt_mode": ("Prompt Optimization Mode", "プロンプト最適化モード", "프롬프트 최적화 모드"),
    "password": ("Proxy Password", "プロキシパスワード", "프록시 비밀번호"),
    "permission_enabled": ("Enable Command Permissions", "コマンド権限を有効化", "명령 권한 활성화"),
    "person_generation": ("Person Generation", "人物生成", "인물 생성"),
    "poll_interval_seconds": ("Poll Interval", "ポーリング間隔", "폴링 간격"),
    "port": ("Proxy Port", "プロキシポート", "프록시 포트"),
    "positive_prompt": ("Default Positive Prompt", "既定のポジティブプロンプト", "기본 포지티브 프롬프트"),
    "positive_prompt_template": (
        "Positive Prompt Template",
        "ポジティブプロンプトテンプレート",
        "포지티브 프롬프트 템플릿",
    ),
    "presets": ("Style Presets", "スタイルプリセット", "스타일 프리셋"),
    "private_default_quota": ("Default Private Quota", "個人チャット既定クォータ", "개인 채팅 기본 할당량"),
    "private_quota_enabled": ("Enable Private Quota", "個人チャットクォータを有効化", "개인 채팅 할당량 활성화"),
    "private_quota_period": ("Private Quota Period", "個人チャットクォータ期間", "개인 채팅 할당량 기간"),
    "prompt_extend": ("Smart Prompt Expansion", "スマートプロンプト拡張", "스마트 프롬프트 확장"),
    "prompt_input_name": ("Prompt Input Field", "プロンプト入力フィールド", "프롬프트 입력 필드"),
    "prompt_review_enabled": ("Enable Prompt Review", "プロンプト審査を有効化", "프롬프트 검토 활성화"),
    "prompt_review_prompt": ("Prompt Review Template", "プロンプト審査テンプレート", "프롬프트 검토 템플릿"),
    "quality": ("Quality", "品質", "품질"),
    "quality_toggle": ("Quality Enhancement", "品質強化", "품질 향상"),
    "qwen_enable_thinking": ("Qwen 3.0 Thinking Mode", "Qwen 3.0 思考モード", "Qwen 3.0 사고 모드"),
    "qwen_extra_parameters": ("Qwen Extra Parameters", "Qwen 追加パラメータ", "Qwen 추가 매개변수"),
    "qwen_prompt_extend_mode": ("Qwen 3.0 Expansion Mode", "Qwen 3.0 拡張モード", "Qwen 3.0 확장 모드"),
    "request_timeout_seconds": ("Image Request Timeout", "画像リクエストのタイムアウト", "이미지 요청 시간 제한"),
    "response_format": ("Response Format", "応答形式", "응답 형식"),
    "review_prompt": ("Review Prompt", "審査プロンプト", "검토 프롬프트"),
    "rewrite_prompt_to_english": ("Rewrite Prompt in English", "英語プロンプトに書き換え", "영어 프롬프트로 재작성"),
    "sampler": ("Sampler", "サンプラー", "샘플러"),
    "scale": ("Prompt Guidance", "プロンプトガイダンス", "프롬프트 가이던스"),
    "scheme": ("Proxy Protocol", "プロキシプロトコル", "프록시 프로토콜"),
    "seed": ("Random Seed", "ランダムシード", "무작위 시드"),
    "seed_input_name": ("Seed Input Field", "シード入力フィールド", "시드 입력 필드"),
    "sequential_image_generation": ("Sequential Image Generation", "組画像生成", "연속 이미지 생성"),
    "size": ("Resolution", "解像度", "해상도"),
    "sm": ("SMEA", "SMEA", "SMEA"),
    "sm_dyn": ("Dynamic SMEA", "ダイナミック SMEA", "동적 SMEA"),
    "steps": ("Sampling Steps", "サンプリングステップ数", "샘플링 단계"),
    "t2i_models": ("Text-to-Image Models", "テキスト画像生成モデル", "텍스트 이미지 생성 모델"),
    "t2i_negative_prompt": (
        "Text-to-Image Negative Prompt",
        "テキスト画像生成ネガティブプロンプト",
        "텍스트 이미지 생성 네거티브 프롬프트",
    ),
    "t2i_negative_prompt_node_id": (
        "Text-to-Image Negative Prompt Node ID",
        "テキスト画像生成ネガティブノード ID",
        "텍스트 이미지 생성 네거티브 노드 ID",
    ),
    "t2i_positive_prompt_node_id": (
        "Text-to-Image Positive Prompt Node ID",
        "テキスト画像生成ポジティブノード ID",
        "텍스트 이미지 생성 포지티브 노드 ID",
    ),
    "t2i_prompt_mode": (
        "Text-to-Image Prompt Mode",
        "テキスト画像生成プロンプトモード",
        "텍스트 이미지 생성 프롬프트 모드",
    ),
    "t2i_prompt_node_id": (
        "Text-to-Image Prompt Node ID",
        "テキスト画像生成プロンプトノード ID",
        "텍스트 이미지 생성 프롬프트 노드 ID",
    ),
    "t2i_seed_node_id": (
        "Text-to-Image Seed Node ID",
        "テキスト画像生成シードノード ID",
        "텍스트 이미지 생성 시드 노드 ID",
    ),
    "t2i_workflow_path": (
        "Text-to-Image Workflow JSON",
        "テキスト画像生成ワークフロー JSON",
        "텍스트 이미지 생성 워크플로 JSON",
    ),
    "text_to_image_unsupported_models": (
        "Models Without Text-to-Image",
        "テキスト画像生成非対応モデル",
        "텍스트 이미지 생성 미지원 모델",
    ),
    "uc_preset": ("Legacy UC Preset", "旧 UC プリセット", "레거시 UC 프리셋"),
    "unified_models": ("Unified Models", "統合モデル", "통합 모델"),
    "use_system_proxy": ("Use System Proxy", "システムプロキシを使用", "시스템 프록시 사용"),
    "user_id": ("End-User ID", "エンドユーザー ID", "최종 사용자 ID"),
    "username": ("Proxy Username", "プロキシユーザー名", "프록시 사용자 이름"),
    "v4_noise_schedule": ("V4 / V4.5 Noise Schedule", "V4 / V4.5 ノイズスケジュール", "V4 / V4.5 노이즈 스케줄"),
    "vidu_extra_parameters": ("Vidu Extra Parameters", "Vidu 追加パラメータ", "Vidu 추가 매개변수"),
    "watermark": ("Add Watermark", "ウォーターマークを追加", "워터마크 추가"),
    "watermark_enabled": ("Enable Watermark", "ウォーターマークを有効化", "워터마크 활성화"),
    "web_search_enabled": ("Enable Web Search", "ウェブ検索を有効化", "웹 검색 활성화"),
    "width": ("Width", "幅", "너비"),
    "zimage_extra_parameters": ("Z-Image Extra Parameters", "Z-Image 追加パラメータ", "Z-Image 추가 매개변수"),
    "zimage_prompt_extend": ("Z-Image Prompt Expansion", "Z-Image プロンプト拡張", "Z-Image 프롬프트 확장"),
}

_FIELD_LABEL_OVERRIDES: Dict[str, Tuple[str, str, str]] = {
    "MiniMaxModelConfig.enabled": ("Enabled", "有効", "활성화"),
    "MiniMaxModelConfig.api_key": ("API Key", "API キー", "API 키"),
    "MiniMaxModelConfig.base_url": ("API Base URL", "API 基本 URL", "API 기본 URL"),
    "MiniMaxModelConfig.models": ("Models", "モデル", "모델"),
    "MiniMaxModelConfig.size": ("Output Size", "出力サイズ", "출력 크기"),
    "MiniMaxModelConfig.model_size_overrides": ("Per-model Sizes", "モデル別サイズ", "모델별 크기"),
    "MiniMaxModelConfig.aspect_ratio": ("Aspect Ratio", "アスペクト比", "화면 비율"),
    "MiniMaxModelConfig.area": ("H3 Area", "H3 面積", "H3 면적"),
    "MiniMaxModelConfig.n": ("Image Count", "生成枚数", "생성 수"),
    "MiniMaxModelConfig.response_format": ("Response Format", "応答形式", "응답 형식"),
    "MiniMaxModelConfig.output_format": ("H3 Output Format", "H3 出力形式", "H3 출력 형식"),
    "MiniMaxModelConfig.output_compression": ("H3 Compression Quality", "H3 圧縮品質", "H3 압축 품질"),
    "MiniMaxModelConfig.stream": ("H3 Streaming", "H3 ストリーミング", "H3 스트리밍"),
    "MiniMaxModelConfig.disable_prompt_enhanced": ("Disable H3 Prompt Enhancement", "H3 プロンプト強化を無効化", "H3 프롬프트 강화 비활성화"),
    "MiniMaxModelConfig.prompt_optimizer": ("image-01 Prompt Optimizer", "image-01 プロンプト最適化", "image-01 프롬프트 최적화"),
    "MiniMaxModelConfig.seed": ("image-01 Seed", "image-01 シード", "image-01 시드"),
    "MiniMaxModelConfig.style_type": ("image-01-live Style", "image-01-live スタイル", "image-01-live 스타일"),
    "MiniMaxModelConfig.style_weight": ("image-01-live Style Weight", "image-01-live スタイル強度", "image-01-live 스타일 가중치"),
    "MiniMaxModelConfig.aigc_watermark": ("Visible AIGC Watermark", "AIGC 可視透かし", "AIGC 표시 워터마크"),
    "MiniMaxModelConfig.request_timeout_seconds": ("MiniMax Request Timeout", "MiniMax リクエスト制限時間", "MiniMax 요청 제한 시간"),
    "MiniMaxModelConfig.extra_parameters": ("Extra Parameters", "追加パラメータ", "추가 매개변수"),
    "MiniMaxModelConfig.rewrite_prompt_to_english": ("Rewrite Prompt in English", "英語プロンプトに変換", "영어 프롬프트로 변환"),
    "PluginSectionConfig.enabled": ("Enable Plugin", "プラグインを有効化", "플러그인 활성화"),
    "StylePresetConfig.enabled": ("Enable Preset", "プリセットを有効化", "프리셋 활성화"),
    "ProxyConfig.enabled": ("Enable Global Proxy", "共通プロキシを有効化", "전역 프록시 활성화"),
    "OpenAICompatibleInstanceConfig.enabled": ("Enable Instance", "インスタンスを有効化", "인스턴스 활성화"),
    "OpenAIModelConfig.enabled": ("Enable This Platform Instance", "このプラットフォームインスタンスを有効化", "이 플랫폼 인스턴스 활성화"),
    "OpenAIModelConfig.api_key": ("OpenAI API Key", "OpenAI API キー", "OpenAI API 키"),
    "OpenAIModelConfig.models": ("OpenAI Models", "OpenAI モデル一覧", "OpenAI 모델 목록"),
    "GoogleModelConfig.enabled": ("Enable Google Platform", "Google プラットフォームを有効化", "Google 플랫폼 활성화"),
    "GoogleModelConfig.api_key": ("Google API Key", "Google API キー", "Google API 키"),
    "GoogleModelConfig.models": ("Google Models", "Google モデル一覧", "Google 모델 목록"),
    "ZhipuModelConfig.enabled": ("Enable Zhipu Platform", "智譜プラットフォームを有効化", "Zhipu 플랫폼 활성화"),
    "ZhipuModelConfig.api_key": ("Zhipu API Key (Required)", "智譜 API キー（必須）", "Zhipu API 키(필수)"),
    "ZhipuModelConfig.models": ("Zhipu Models (Required)", "智譜モデル一覧（必須）", "Zhipu 모델 목록(필수)"),
    "ZhipuModelConfig.quality": ("Generation Quality (Optional)", "生成品質（任意）", "생성 품질(선택 사항)"),
    "ZhipuModelConfig.size": ("Resolution (Optional)", "解像度（任意）", "해상도(선택 사항)"),
    "ZhipuModelConfig.watermark_enabled": (
        "Enable Watermark (Optional)",
        "ウォーターマークを有効化（任意）",
        "워터마크 활성화(선택 사항)",
    ),
    "ZhipuModelConfig.user_id": ("End-User ID (Optional)", "エンドユーザー ID（任意）", "최종 사용자 ID(선택 사항)"),
    "ZhipuModelConfig.extra_parameters": (
        "Extra Parameters (Optional)",
        "追加パラメータ（任意）",
        "추가 매개변수(선택 사항)",
    ),
    "AliyunModelConfig.enabled": (
        "Enable Alibaba Cloud Platform",
        "Alibaba Cloud を有効化",
        "Alibaba Cloud 플랫폼 활성화",
    ),
    "AliyunModelConfig.base_url": (
        "DashScope Base URL (Required)",
        "DashScope ベース URL（必須）",
        "DashScope 기본 URL(필수)",
    ),
    "AliyunModelConfig.api_key": (
        "DashScope API Key (Required)",
        "DashScope API キー（必須）",
        "DashScope API 키(필수)",
    ),
    "AliyunModelConfig.models": (
        "Alibaba Cloud Models (Required)",
        "Alibaba Cloud モデル一覧（必須）",
        "Alibaba Cloud 모델 목록(필수)",
    ),
    "VolcengineModelConfig.enabled": (
        "Enable Volcengine Platform",
        "Volcengine プラットフォームを有効化",
        "Volcengine 플랫폼 활성화",
    ),
    "VolcengineModelConfig.base_url": (
        "Volcengine Base URL",
        "Volcengine ベース URL",
        "Volcengine 기본 URL",
    ),
    "VolcengineModelConfig.api_key": ("Volcengine API Key", "Volcengine API キー", "Volcengine API 키"),
    "VolcengineModelConfig.models": (
        "Volcengine Image Models",
        "Volcengine 画像モデル一覧",
        "Volcengine 이미지 모델 목록",
    ),
    "SiliconFlowModelConfig.enabled": (
        "Enable SiliconFlow Platform",
        "SiliconFlow プラットフォームを有効化",
        "SiliconFlow 플랫폼 활성화",
    ),
    "SiliconFlowModelConfig.api_key": ("SiliconFlow API Key", "SiliconFlow API キー", "SiliconFlow API 키"),
    "SiliconFlowModelConfig.models": ("SiliconFlow Models", "SiliconFlow モデル一覧", "SiliconFlow 모델 목록"),
    "NovelAIModelConfig.enabled": (
        "Enable NovelAI / NovelAPI",
        "NovelAI / NovelAPI を有効化",
        "NovelAI / NovelAPI 활성화",
    ),
    "NovelAIModelConfig.api_key": ("NovelAI API Key", "NovelAI API キー", "NovelAI API 키"),
    "NovelAIModelConfig.models": ("NovelAI Models", "NovelAI モデル一覧", "NovelAI 모델 목록"),
    "ComfyUIModelConfig.enabled": ("Enable ComfyUI", "ComfyUI を有効化", "ComfyUI 활성화"),
    "PromptModerationConfig.enabled": ("Enable Prompt Review", "プロンプト審査を有効化", "프롬프트 검토 활성화"),
    "PromptModerationConfig.review_prompt": ("Prompt Review Instructions", "プロンプト審査指示", "프롬프트 검토 지침"),
    "ImageModerationConfig.enabled": (
        "Enable Generated Image Review",
        "生成画像の審査を有効化",
        "생성 이미지 검토 활성화",
    ),
    "ImageModerationConfig.review_prompt": ("Image Review Instructions", "画像審査指示", "이미지 검토 지침"),
}

_PLACEHOLDER_TEXTS: Dict[str, Tuple[str, str, str]] = {
    "StylePresetConfig.name": ("e.g. Watercolor or Cyberpunk", "例：水彩、サイバーパンク", "예: 수채화, 사이버펑크"),
    "OpenAICompatibleInstanceConfig.name": (
        "e.g. platform-1 or newapi-1",
        "例：platform-1、newapi-1",
        "예: platform-1, newapi-1",
    ),
}

_OPENAI_MODE_HINTS = (
    "auto / images_api / chat_completions (New API image chat) / rinkoai (RinkoAI NAI). "
    "auto uses endpoint metadata and model families. Legacy novelai_images_api means rinkoai.",
    "auto / images_api / chat_completions（New API 画像チャット）/ rinkoai（RinkoAI NAI）。"
    "auto は端点情報とモデル系列を使用します。旧 novelai_images_api は rinkoai の別名です。",
    "auto / images_api / chat_completions(New API 이미지 채팅) / rinkoai(RinkoAI NAI). "
    "auto는 엔드포인트 정보와 모델 계열을 사용합니다. 이전 novelai_images_api는 rinkoai의 별칭입니다.",
)


_FIELD_HINT_OVERRIDES: Dict[str, Tuple[str, str, str]] = {
    "MiniMaxModelConfig.enabled": ("Enabled. See the MiniMax model-specific limits in the platform guide.", "有効。モデルごとの制約はプラットフォームガイドを参照してください。", "활성화. 모델별 제한은 플랫폼 가이드를 참조하세요."),
    "MiniMaxModelConfig.api_key": ("API Key. See the MiniMax model-specific limits in the platform guide.", "API キー。モデルごとの制約はプラットフォームガイドを参照してください。", "API 키. 모델별 제한은 플랫폼 가이드를 참조하세요."),
    "MiniMaxModelConfig.base_url": ("API Base URL. See the MiniMax model-specific limits in the platform guide.", "API 基本 URL。モデルごとの制約はプラットフォームガイドを参照してください。", "API 기본 URL. 모델별 제한은 플랫폼 가이드를 참조하세요."),
    "MiniMaxModelConfig.models": ("Defaults to MiniMax-H3-Image. Add H3 Highspeed or image-01 variants from the documented presets; image-01 editing is character reference only.", "既定は MiniMax-H3-Image。公式プリセットから他の H3/image-01 を追加できます。image-01 の編集は人物参照です。", "기본 모델은 MiniMax-H3-Image입니다. 공식 문서 프리셋에서 다른 H3/image-01 모델을 추가하세요. image-01 편집은 인물 참조입니다."),
    "MiniMaxModelConfig.size": ("auto or WIDTHxHEIGHT. H3 explicit dimensions cannot be combined with aspect_ratio/area. image-01 dimensions must be multiples of 8 in 512–2048; not supported by live.", "auto または 幅x高さ。H3 の固定サイズは比率・面積と併用不可。image-01 は 512～2048 の8の倍数、live は固定サイズ不可。", "auto 또는 너비x높이. H3 고정 크기는 비율/면적과 함께 사용할 수 없습니다. image-01은 512~2048 범위의 8의 배수이며 live에는 고정 크기를 지원하지 않습니다."),
    "MiniMaxModelConfig.model_size_overrides": ("Per-model Sizes. See the MiniMax model-specific limits in the platform guide.", "モデル別サイズ。モデルごとの制約はプラットフォームガイドを参照してください。", "모델별 크기. 모델별 제한은 플랫폼 가이드를 참조하세요."),
    "MiniMaxModelConfig.aspect_ratio": ("Aspect Ratio. See the MiniMax model-specific limits in the platform guide.", "アスペクト比。モデルごとの制約はプラットフォームガイドを参照してください。", "화면 비율. 모델별 제한은 플랫폼 가이드를 참조하세요."),
    "MiniMaxModelConfig.area": ("H3 only, with size=auto. Leave blank for the server default of 4K; choose 1K/2K to reduce output area.", "H3 の size=auto のみ。空欄はサーバー既定の 4K。面積を抑えるには 1K/2K を選択します。", "H3의 size=auto에서만 사용합니다. 비우면 서버 기본 4K이며 면적을 줄이려면 1K/2K를 선택하세요."),
    "MiniMaxModelConfig.n": ("H3: 1–10; image-01: 1–9. Partial success returns only successful images without regenerating failed items.", "H3 は1～10枚、image-01 は1～9枚。部分成功時は成功画像のみ返し、失敗分を再生成しません。", "H3는 1~10장, image-01은 1~9장입니다. 일부 성공 시 성공한 이미지만 반환하고 실패 이미지를 다시 생성하지 않습니다."),
    "MiniMaxModelConfig.response_format": ("Response Format. See the MiniMax model-specific limits in the platform guide.", "応答形式。モデルごとの制約はプラットフォームガイドを参照してください。", "응답 형식. 모델별 제한은 플랫폼 가이드를 참조하세요."),
    "MiniMaxModelConfig.output_format": ("H3 Output Format. See the MiniMax model-specific limits in the platform guide.", "H3 出力形式。モデルごとの制約はプラットフォームガイドを参照してください。", "H3 출력 형식. 모델별 제한은 플랫폼 가이드를 참조하세요."),
    "MiniMaxModelConfig.output_compression": ("H3 Compression Quality. See the MiniMax model-specific limits in the platform guide.", "H3 圧縮品質。モデルごとの制約はプラットフォームガイドを参照してください。", "H3 압축 품질. 모델별 제한은 플랫폼 가이드를 참조하세요."),
    "MiniMaxModelConfig.stream": ("H3 only and URL responses only. Results are collected in image-index order; interrupted streams never resubmit generation.", "H3 の URL 応答のみ。画像番号順に収集し、ストリーム切断時も再生成しません。", "H3의 URL 응답에만 적용됩니다. 이미지 인덱스 순서로 수집하며 스트림 중단 시 다시 생성하지 않습니다."),
    "MiniMaxModelConfig.disable_prompt_enhanced": ("H3 text-to-image only. Disabling enhancement requires explicit dimensions or a fixed ratio. Editing always uses enhancement.", "H3 文生図のみ。無効化時は固定サイズか比率が必須。画像編集は常に強化を使用します。", "H3 텍스트 이미지 생성에만 적용됩니다. 끄려면 고정 크기나 비율을 지정해야 하며 편집은 항상 강화를 사용합니다."),
    "MiniMaxModelConfig.prompt_optimizer": ("image-01 Prompt Optimizer. See the MiniMax model-specific limits in the platform guide.", "image-01 プロンプト最適化。モデルごとの制約はプラットフォームガイドを参照してください。", "image-01 프롬프트 최적화. 모델별 제한은 플랫폼 가이드를 참조하세요."),
    "MiniMaxModelConfig.seed": ("image-01 only. -1 omits the parameter; zero is a valid seed. H3 does not declare a seed parameter.", "image-01 のみ。-1 は未送信、0 は有効です。H3 は seed 非対応です。", "image-01에만 사용합니다. -1이면 생략하며 0은 유효한 시드입니다. H3는 seed를 지원하지 않습니다."),
    "MiniMaxModelConfig.style_type": ("image-01-live Style. See the MiniMax model-specific limits in the platform guide.", "image-01-live スタイル。モデルごとの制約はプラットフォームガイドを参照してください。", "image-01-live 스타일. 모델별 제한은 플랫폼 가이드를 참조하세요."),
    "MiniMaxModelConfig.style_weight": ("image-01-live Style Weight. See the MiniMax model-specific limits in the platform guide.", "image-01-live スタイル強度。モデルごとの制約はプラットフォームガイドを参照してください。", "image-01-live 스타일 가중치. 모델별 제한은 플랫폼 가이드를 참조하세요."),
    "MiniMaxModelConfig.aigc_watermark": ("Visible AIGC Watermark. See the MiniMax model-specific limits in the platform guide.", "AIGC 可視透かし。モデルごとの制約はプラットフォームガイドを参照してください。", "AIGC 표시 워터마크. 모델별 제한은 플랫폼 가이드를 참조하세요."),
    "MiniMaxModelConfig.request_timeout_seconds": ("Instance timeout in seconds, default/minimum 600. MiniMax is non-idempotent: timeout and result-read failures never regenerate.", "インスタンスごとの秒数、既定・最小600秒。MiniMax は冪等でなく、タイムアウトや結果読込失敗時も再生成しません。", "인스턴스별 제한 시간(초)으로 기본/최솟값은 600입니다. MiniMax는 멱등하지 않으며 시간 초과나 결과 읽기 실패 시 다시 생성하지 않습니다."),
    "MiniMaxModelConfig.extra_parameters": ("KEY=VALUE extensions. Cannot replace model, prompt or source images, or mix known H3/image-01 protocol fields.", "名前=値。モデル・プロンプト・元画像の上書きや H3/image-01 の異なるプロトコル項目の混在は禁止です。", "이름=값 형식의 확장입니다. 모델, 프롬프트, 원본 이미지를 덮어쓰거나 H3/image-01의 서로 다른 프로토콜 필드를 혼합할 수 없습니다."),
    "MiniMaxModelConfig.rewrite_prompt_to_english": ("Rewrite Prompt in English. See the MiniMax model-specific limits in the platform guide.", "英語プロンプトに変換。モデルごとの制約はプラットフォームガイドを参照してください。", "영어 프롬프트로 변환. 모델별 제한은 플랫폼 가이드를 참조하세요."),
    "GeneralConfig.integration_api_enabled": (
        "On by default. Disable all public plugin integration APIs. Workspace, chat commands and AI tools remain available. Accepted tasks continue.",
        "既定は有効です。無効にすると公開連携 API を拒否します。ワークスペース、コマンド、AI ツールは使用可能で、受理済みタスクは継続します。",
        "기본적으로 켜져 있습니다. 끄면 모든 공개 연동 API를 거부합니다. 작업 공간, 명령, AI 도구는 계속 사용할 수 있으며 접수된 작업도 계속 실행됩니다.",
    ),
    "GeneralConfig.group_access_mode": (
        "Blacklist by default: an empty list allows all groups. An empty whitelist denies all groups. Administrators follow the same rules.",
        "既定はブラックリストで、空欄なら全グループを許可します。空のホワイトリストは全グループを拒否します。管理者も対象です。",
        "기본은 차단 목록이며 빈 목록은 모든 그룹을 허용합니다. 빈 허용 목록은 모든 그룹을 거부합니다. 관리자에게도 적용됩니다.",
    ),
    "GeneralConfig.group_access_ids": (
        "One group number per entry; use group OpenID for the official QQ adapter. Do not enter stream IDs, session hashes or member QQ numbers.",
        "各項目にグループ番号を入力します。QQ 公式アダプターはグループ OpenID を使用します。stream ID、会話ハッシュ、メンバー番号は不要です。",
        "항목마다 그룹 번호를 입력합니다. QQ 공식 어댑터는 그룹 OpenID를 사용합니다. 스트림 ID, 대화 해시, 멤버 QQ 번호는 입력하지 마세요.",
    ),
    "GeneralConfig.private_access_mode": (
        "Blacklist by default: an empty list allows all private chats. An empty whitelist denies all private chats. Does not restrict users inside groups.",
        "既定はブラックリストで、空欄なら全個人チャットを許可します。空のホワイトリストは全個人チャットを拒否します。グループ内での利用には影響しません。",
        "기본은 차단 목록이며 빈 목록은 모든 개인 대화를 허용합니다. 빈 허용 목록은 모든 개인 대화를 거부합니다. 그룹 내 사용에는 영향을 주지 않습니다.",
    ),
    "GeneralConfig.private_access_ids": (
        "One QQ number per entry; use user OpenID for the official QQ adapter. No stream ID or session hash is needed. OpenIDs are matched exactly.",
        "各項目に QQ 番号を入力します。QQ 公式アダプターはユーザー OpenID を使用します。stream ID や会話ハッシュは不要です。OpenID は完全一致で照合します。",
        "항목마다 QQ 번호를 입력합니다. QQ 공식 어댑터는 사용자 OpenID를 사용합니다. 스트림 ID나 대화 해시는 필요하지 않습니다. OpenID는 정확히 일치해야 합니다.",
    ),
    "GeneralConfig.sync_generated_images_to_history": (
        "Off by default. After successful delivery, let a visual Planner view generated images; a text Planner uses image descriptions. May increase visual context and background recognition costs. Tasks without chat delivery and command reply cards are unaffected.",
        "既定は無効です。送信成功後、視覚 Planner は生成画像を参照でき、テキスト Planner は画像説明を使用します。視覚コンテキストとバックグラウンド画像認識のコストが増える場合があります。会話に送信しないタスクとコマンド応答カードには適用しません。",
        "기본적으로 꺼져 있습니다. 전송 성공 후 시각 Planner는 생성 이미지를 볼 수 있고 텍스트 Planner는 이미지 설명을 사용합니다. 시각 컨텍스트 및 백그라운드 이미지 인식 비용이 늘어날 수 있습니다. 대화로 전송하지 않는 작업과 명령 응답 카드에는 적용하지 않습니다.",
    ),
    "StyleConfig.default_style": (
        "Automatically applied when AI tools, ordinary drawing commands, the workspace or plugin APIs omit a style. Select an enabled preset. Leave blank to disable automatic styling; explicitly choose no style to skip it for one request.",
        "AI ツール、通常の描画コマンド、ワークスペース、プラグイン API でスタイル未指定の場合に自動適用します。有効なプリセットを選択してください。空欄は自動適用なしで、明示的にスタイルなしを選べば今回だけ省略できます。",
        "AI 도구, 일반 그리기 명령, 작업 공간, 플러그인 API가 스타일을 생략하면 자동 적용합니다. 활성 프리셋을 선택하세요. 비워 두면 자동 적용하지 않으며 명시적으로 스타일 없음을 선택하면 이번 요청에서 건너뜁니다.",
    ),
    "negative_prompt_enabled": (
        "When disabled, ignore negative prompts from AI tools, commands, the workspace and APIs, including this instance's defaults. Style presets keep their own positive and negative content.",
        "無効時は AI ツール、コマンド、ワークスペース、API のネガティブプロンプトと、このインスタンスの既定値を無視します。スタイル固有の正負プロンプトは保持されます。",
        "비활성화하면 AI 도구, 명령, 작업 공간, API의 네거티브 프롬프트와 이 인스턴스의 기본값을 무시합니다. 스타일 자체의 긍정 및 부정 내용은 유지됩니다.",
    ),
    "negative_prompt": (
        "Used only when negative prompts are enabled. Append to the request, remove duplicate terms with the style preset, and include in English rewriting. Providers without a separate negative field receive the merged prompt.",
        "ネガティブプロンプトが有効な場合のみ使用します。今回の入力に追加し、スタイルとの重複語を除去して英語書き換えにも含めます。専用フィールドのないサービスでは本文に統合します。",
        "네거티브 프롬프트가 활성화된 경우에만 사용합니다. 요청 뒤에 추가하고 스타일과 중복되는 항목을 제거하며 영어 변환에도 포함합니다. 별도 필드가 없는 제공자는 본문에 합칩니다.",
    ),
    "GeneralConfig.prompt_review_retry_count": (
        "Default: 2 extra retries, at most 3 calls. Range 0–5; 0 disables retries. Explicit rejection and cancellation never retry.",
        "既定は追加 2 回、最大 3 回の呼び出しです。範囲は 0～5、0 で無効。明確な拒否とキャンセルは再試行しません。",
        "기본 추가 2회, 최대 3회 호출합니다. 범위 0~5, 0이면 재시도하지 않습니다. 명시적 거부와 취소는 재시도하지 않습니다.",
    ),
    "GeneralConfig.image_review_retry_count": (
        "Default: 2 extra retries, at most 3 calls. Range 0–5. Retry only review of the same image, never generation; rejection and cancellation do not retry.",
        "既定は追加 2 回、最大 3 回の呼び出しです。範囲は 0～5。同じ画像の審査だけを再試行し、再生成は行いません。拒否とキャンセルは再試行しません。",
        "기본 추가 2회, 최대 3회 호출합니다. 범위 0~5. 같은 이미지의 검토만 재시도하고 이미지를 다시 생성하지 않습니다. 거부와 취소는 재시도하지 않습니다.",
    ),
    "GeneralConfig.prompt_review_model": (
        "Default: vlm. Use the models configured for the Host replyer, planner or vlm task group.",
        "既定は vlm。Host の replyer、planner、vlm タスクグループに設定されたモデルを使用します。",
        "기본값은 vlm입니다. Host의 replyer, planner 또는 vlm 작업 그룹에 설정된 모델을 사용합니다.",
    ),
    "GeneralConfig.image_review_model": (
        "Default: vlm. replyer and planner are also available, but every model in the selected group must support images or review fails.",
        "既定は vlm。replyer と planner も選択できますが、選択したグループのモデルが画像入力に対応していない場合は審査に失敗します。",
        "기본값은 vlm입니다. replyer와 planner도 선택할 수 있지만 선택한 그룹의 모델이 이미지 입력을 지원하지 않으면 검토에 실패합니다.",
    ),
    "GeneralConfig.prompt_review_timeout_seconds": (
        "Default: 60 seconds per attempt, range 5–600; retries have separate budgets. Continue immediately when review finishes, without bypassing failed review.",
        "1 回の既定は 60 秒、範囲は 5～600 秒。再試行は別の待機枠です。完了後すぐに続行し、失敗した審査は省略しません。",
        "시도당 기본 60초, 범위 5~600초. 재시도마다 별도의 대기 시간을 사용합니다. 검토 완료 시 즉시 진행하며 실패한 검토를 생략하지 않습니다.",
    ),
    "GeneralConfig.image_review_timeout_seconds": (
        "Default: 60 seconds per image per attempt, range 5–600; retries are separate. Independent of generation and prompt review. Failed review never releases or regenerates images.",
        "画像 1 枚の 1 回あたり既定 60 秒、範囲 5～600 秒。再試行は別枠で、画像生成・プロンプト審査とは独立しています。失敗した審査で送信や再生成は行いません。",
        "이미지별 시도당 기본 60초, 범위 5~600초. 재시도는 별도로 계산하며 생성 및 프롬프트 검토와 독립적입니다. 검토 실패 시 전송하거나 다시 생성하지 않습니다.",
    ),
    "GeneralConfig.skip_image_url_ip_check": (
        "Off by default. Enable only for trusted services to allow private or special-DNS image hosts. HTTP(S) URL and redirect checks remain. Proxied hostnames are always resolved by the proxy.",
        "既定は無効です。信頼できるサービスの内部ネットワークや特殊 DNS の画像ホストにのみ使用してください。HTTP(S) URL と各リダイレクトの検証は継続します。プロキシ経由のドメインは常にプロキシ側で解決します。",
        "기본적으로 꺼져 있습니다. 신뢰할 수 있는 서비스의 사설망 또는 특수 DNS 이미지 호스트에만 사용하세요. HTTP(S) URL 및 리디렉션 검사는 유지됩니다. 프록시를 사용하는 도메인은 항상 프록시에서 해석합니다.",
    ),
    "NovelAIModelConfig.models": (
        "Add official presets or enter compatible-service model IDs in this single list. Save the platform to apply changes.",
        "公式プリセットの追加と互換サービスのモデル ID の入力を同じ一覧で行います。プラットフォームを保存すると反映されます。",
        "공식 프리셋 추가와 호환 서비스 모델 ID 입력을 하나의 목록에서 관리합니다. 플랫폼을 저장하면 적용됩니다.",
    ),
    "NovelAIModelConfig.custom_models": (
        "Legacy custom models are merged into the unified model list and are no longer edited separately.",
        "旧カスタムモデルは統一モデル一覧へ統合され、個別には編集しません。",
        "기존 사용자 지정 모델은 통합 모델 목록에 병합되며 별도로 편집하지 않습니다.",
    ),
    "AgnesModelConfig.base_url": (
        "Use the API base URL, not the console or documentation URL.",
        "コンソールやドキュメントではなく API のベース URL を入力します。",
        "콘솔이나 문서 주소가 아닌 API 기본 URL을 입력하세요.",
    ),
    "AgnesModelConfig.models": (
        "Image models available to your account, supporting generation and editing with multiple reference images.",
        "アカウントで利用可能な画像モデルを指定します。画像生成と複数の参照画像による編集に対応します。",
        "계정에서 사용 가능한 이미지 모델을 입력하세요. 이미지 생성과 여러 참조 이미지 편집을 지원합니다.",
    ),
    "AgnesModelConfig.default_size": (
        "For 2.1 / 2.5, prefer 1K–4K tiers with an aspect ratio; pixel dimensions are also accepted but may be adjusted. Use only pixel dimensions for 2.0, with per-model overrides below.",
        "2.1 / 2.5 は 1K～4K と縦横比の組み合わせを推奨します。ピクセル寸法も指定できますが、調整される場合があります。2.0 はピクセル寸法のみを使用し、下でモデル別に上書きできます。",
        "2.1 / 2.5는 1K~4K와 화면 비율 조합을 권장합니다. 픽셀 크기도 사용할 수 있지만 조정될 수 있습니다. 2.0은 픽셀 크기만 사용하며 아래에서 모델별로 설정할 수 있습니다.",
    ),
    "AgnesModelConfig.ratio": (
        "Aspect ratio for tier-based sizes in 2.1 / 2.5; omitted for 2.0, which uses pixel dimensions.",
        "2.1 / 2.5 の段階サイズ用の縦横比です。ピクセル寸法を使う 2.0 には送信しません。",
        "2.1 / 2.5의 단계별 크기에 사용하는 비율입니다. 픽셀 크기를 사용하는 2.0에는 전송하지 않습니다.",
    ),
    "AgnesModelConfig.response_format": (
        "Automatically uses the nested parameters required by Agnes.",
        "Agnes が要求するネストされたパラメーターを自動的に使用します。",
        "Agnes에서 요구하는 중첩 매개변수 형식을 자동으로 사용합니다.",
    ),
    "AgnesModelConfig.extra_parameters": (
        "Add provider extensions only when needed; extra_body must be a JSON object.",
        "必要な拡張パラメーターのみ追加します。extra_body は JSON オブジェクトで指定します。",
        "필요할 때만 확장 매개변수를 추가하세요. extra_body는 JSON 객체여야 합니다.",
    ),
    "OpenAIModelConfig.enabled": (
        "When disabled, this instance's models are excluded from routing. Other platform instances can remain enabled independently.",
        "無効にすると、このインスタンスのモデルはルーティング対象外になります。他のプラットフォームインスタンスは個別に有効化できます。",
        "비활성화하면 이 인스턴스의 모델은 라우팅에서 제외됩니다. 다른 플랫폼 인스턴스는 개별적으로 활성화할 수 있습니다.",
    ),
    "StylePresetConfig.positive_prompt_template": (
        "{prompt} inserts this request's drawing description. Keep it and add style words around it: watercolor, {prompt} + a cat becomes watercolor, a cat. Without it, the description is appended automatically. NovelAI {{tag}} weights are preserved.",
        "{prompt} は今回の描画内容に置換されます。残したまま前後にスタイルを追加してください。例：水彩、{prompt} に「猫」を入力すると「水彩、猫」になります。削除した場合も描画内容を末尾に追加します。NovelAI の {{tag}} は保持されます。",
        "{prompt}는 이번 요청의 그림 설명으로 바뀝니다. 유지하고 앞뒤에 스타일을 추가하세요. 예: 수채화, {prompt}에 고양이를 입력하면 수채화, 고양이가 됩니다. 삭제해도 설명을 뒤에 추가하며 NovelAI {{tag}} 가중치는 유지합니다.",
    ),
    "StylePresetConfig.negative_prompt_template": (
        "{negative_prompt} inserts request and instance default negatives, with duplicate terms removed. When the instance disables negatives, its inputs and defaults are cleared while the template's own content remains. Without the placeholder, negatives are appended. Providers without a separate field receive merged text.",
        "{negative_prompt} には今回の入力とインスタンスの既定値を挿入し、重複語を除去します。無効時は入力と既定値を空にし、テンプレート固有の内容を保持します。プレースホルダーがなくても末尾に追加し、専用フィールドのないサービスでは本文に統合します。",
        "{negative_prompt}에는 요청과 인스턴스 기본값을 넣고 중복 항목을 제거합니다. 비활성화하면 입력과 기본값은 비우고 템플릿 자체의 내용은 유지합니다. 자리표시자가 없어도 뒤에 추가하며 별도 필드가 없는 제공자는 본문에 합칩니다.",
    ),
    "PluginSectionConfig.image_cache_max_mb": (
        "Default 300 MB for originals and WebP previews in the plugin temporary directory. Old images are removed automatically; task records remain.",
        "既定は 300 MB。プラグイン一時ディレクトリの原画像と WebP プレビューが対象です。古い画像を自動削除し、タスク記録は保持します。",
        "기본 300 MB. 플러그인 임시 폴더의 원본과 WebP 미리보기에 적용하며, 오래된 이미지를 자동 삭제하고 작업 기록은 보존합니다.",
    ),
    "PluginSectionConfig.log_max_mb": (
        "Default 10 MB across the current log and all rotated backups. Old logs are removed automatically.",
        "既定は 10 MB。現在のログと全ローテーションバックアップの合計です。古いログを自動削除します。",
        "기본 10 MB. 현재 로그와 모든 순환 백업의 합계이며 오래된 로그를 자동 삭제합니다.",
    ),
    "PluginSectionConfig.upload_cache_max_mb": (
        "Default 256 MB, minimum 40 MB. Uploads and input images also expire after 24 hours or 100 files.",
        "既定は 256 MB、最小 40 MB。アップロードと入力画像は 24 時間または 100 ファイルの上限でも削除します。",
        "기본 256 MB, 최소 40 MB. 업로드와 입력 이미지는 24시간 또는 100개 파일 제한도 적용합니다.",
    ),
    "GeneralConfig.default_model": (
        "Leave empty to automatically choose an available model, or select a model from a specific platform instance.",
        "空欄では利用可能なモデルを自動選択します。特定のプラットフォームのモデルも選択できます。",
        "비워 두면 사용 가능한 모델을 자동으로 선택하며 특정 플랫폼 인스턴스의 모델을 지정할 수도 있습니다.",
    ),
    "GeneralConfig.fallback_models": (
        "Add models as needed and reorder them. Move to the next model after retries are exhausted; empty disables fallback.",
        "必要なモデルを追加して順序を変更します。再試行後に次のモデルへ進みます。空欄で無効です。",
        "필요한 모델을 추가하고 순서를 변경하세요. 재시도 소진 후 다음 모델을 시도하며 비어 있으면 사용하지 않습니다.",
    ),
    "GeneralConfig.request_retry_count": (
        "Default: 1 extra attempt; configurable from 0 to 5, only for safe failures such as an unestablished connection or explicit rate limiting. Never regenerate after review rejection, result download failure, or an uncertain remote outcome.",
        "既定は追加1回、0～5回で設定できます。接続未確立や明示的なレート制限など安全な失敗のみ再試行します。審査拒否、結果取得失敗、リモート状態不明時は再生成しません。",
        "기본 추가 재시도 1회, 0~5회로 설정합니다. 연결 전 실패나 명시적 속도 제한 등 안전한 실패만 재시도합니다. 심사 거부, 결과 다운로드 실패, 원격 처리 상태 불명 시 재생성하지 않습니다.",
    ),
    "ComfyUIModelConfig.t2i_workflow_path": (
        "The data/ prefix maps to the plugin data directory; default: data/workflows/t2i.json. Other relative paths remain relative to the plugin source directory. Absolute paths are supported. Export an API-format workflow from ComfyUI.",
        "data/ 接頭辞はプラグインの標準データディレクトリに対応します。既定値は data/workflows/t2i.json。その他の相対パスはプラグインのソースディレクトリが基準です。絶対パスも使用できます。ComfyUI の API 形式でエクスポートしてください。",
        "data/ 접두사는 플러그인 표준 데이터 디렉터리에 매핑됩니다. 기본값: data/workflows/t2i.json. 다른 상대 경로는 플러그인 소스 디렉터리 기준이며 절대 경로도 지원합니다. ComfyUI API 형식으로 내보내세요.",
    ),
    "ComfyUIModelConfig.i2i_workflow_path": (
        "The data/ prefix maps to the plugin data directory; default: data/workflows/i2i.json. Other relative paths remain relative to the plugin source directory. Absolute paths are supported. Include a node that reads the uploaded image.",
        "data/ 接頭辞はプラグインの標準データディレクトリに対応します。既定値は data/workflows/i2i.json。その他の相対パスはプラグインのソースディレクトリが基準です。絶対パスも使用できます。アップロード画像を読み込むノードが必要です。",
        "data/ 접두사는 플러그인 표준 데이터 디렉터리에 매핑됩니다. 기본값: data/workflows/i2i.json. 다른 상대 경로는 플러그인 소스 디렉터리 기준이며 절대 경로도 지원합니다. 업로드 이미지를 읽는 노드가 필요합니다.",
    ),
    "GoogleModelConfig.image_size": (
        "1K / 2K / 4K; Gemini 3.1 Flash also supports 512. Use uppercase K; leave blank for the model default.",
        "1K / 2K / 4K。Gemini 3.1 Flash は 512 にも対応します。大文字 K を使用し、空欄はモデルの既定値を使用します。",
        "1K / 2K / 4K. Gemini 3.1 Flash는 512도 지원합니다. 대문자 K를 사용하며 비워 두면 모델 기본값을 사용합니다.",
    ),
    "SiliconFlowModelConfig.cfg": (
        "Qwen Image only; 0 omits the parameter. A common value is 4. Kolors uses guidance_scale instead.",
        "Qwen Image のみ使用します。0 は送信しません。一般的な値は 4 です。Kolors は guidance_scale を使用します。",
        "Qwen Image 전용입니다. 0이면 전송하지 않습니다. 일반적인 값은 4입니다. Kolors는 guidance_scale을 사용합니다.",
    ),
    "AliyunModelConfig.models": (
        "Required. Defaults include Qwen 3.0/2.0, Z-Image, Kling v3 and current Vidu image models. "
        "Add older models or dated snapshots manually when needed.",
        "必須。既定は Qwen 3.0/2.0、Z-Image、Kling v3 と現行の Vidu 画像モデルです。"
        "旧モデルや日付付きスナップショットは必要に応じて手動で追加できます。",
        "필수. 기본 목록에는 Qwen 3.0/2.0, Z-Image, Kling v3와 현재 Vidu 이미지 모델만 포함됩니다. "
        "이전 모델과 날짜별 스냅샷은 필요할 때 직접 추가할 수 있습니다.",
    ),
    "ZhipuModelConfig.quality": (
        "Leave blank for the model default. GLM-Image supports hd; CogView supports hd or standard.",
        "空欄はモデルの既定値を使用します。GLM-Image は hd、CogView は hd または standard に対応します。",
        "비워 두면 모델 기본값을 사용합니다. GLM-Image는 hd, CogView는 hd 또는 standard를 지원합니다.",
    ),
    "VolcengineModelConfig.output_format": (
        "Enter png or jpeg, or leave blank for the model default. Supported by Seedream 5.0 models only.",
        "png または jpeg を入力します。空欄はモデルの既定値を使用します。Seedream 5.0 系列のみ対応します。",
        "png 또는 jpeg를 입력합니다. 비워 두면 모델 기본값을 사용합니다. Seedream 5.0 계열만 지원합니다.",
    ),
    "VolcengineModelConfig.optimize_prompt_mode": (
        "Enter standard or fast; leave blank to omit. fast is supported by Seedream 5.0 pro and 4.0 only.",
        "standard または fast を入力します。空欄は送信しません。fast は Seedream 5.0 pro と 4.0 のみ対応します。",
        "standard 또는 fast를 입력합니다. 비워 두면 전송하지 않습니다. fast는 Seedream 5.0 pro와 4.0만 지원합니다.",
    ),
    "VolcengineModelConfig.background": (
        "Enter opaque or transparent; leave blank to omit. Seedream 5.0 pro/flash edits only. "
        "transparent requires one transparent source image and non-JPEG output.",
        "opaque または transparent を入力します。空欄は送信しません。Seedream 5.0 pro/flash の画像変換のみ対応します。"
        "transparent は透過した元画像 1 枚が必要で、JPEG 出力は使用できません。",
        "opaque 또는 transparent를 입력합니다. 비워 두면 전송하지 않습니다. Seedream 5.0 pro/flash 이미지 변환만 지원합니다. "
        "transparent는 투명 원본 이미지 한 장이 필요하며 JPEG 출력은 사용할 수 없습니다.",
    ),
}


def _localized_field_entries(
    class_name: str,
    field_name: str,
    json_schema_extra: Dict[str, object],
) -> Dict[str, Dict[str, str]]:
    """生成一个字段的三语 WebUI 元数据。"""

    field_path = f"{class_name}.{field_name}"
    labels = _FIELD_LABEL_OVERRIDES.get(field_path, _FIELD_LABELS.get(field_name))
    if labels is None:
        raise ValueError(f"配置字段缺少 i18n 标签：{field_path}")

    placeholder_values = _PLACEHOLDER_TEXTS.get(field_path)
    default_placeholder = str(json_schema_extra.get("placeholder") or "").strip()
    translations: Dict[str, Dict[str, str]] = {}
    for index, locale in enumerate(_LOCALES):
        label = labels[index]
        localized: Dict[str, str] = {"label": label}
        if str(json_schema_extra.get("hint") or "").strip():
            hints = _FIELD_HINT_OVERRIDES.get(field_path, _FIELD_HINT_OVERRIDES.get(field_name))
            if hints is not None:
                localized["hint"] = hints[index]
            elif field_name == "default_openai_compatibility_mode":
                localized["hint"] = _OPENAI_MODE_HINTS[index]
            elif locale == "en_US":
                localized["hint"] = f"Configure {label}."
            elif locale == "ja_JP":
                localized["hint"] = f"{label}を設定します。"
            else:
                localized["hint"] = f"{label}을(를) 설정합니다."
        if default_placeholder:
            localized["placeholder"] = (
                placeholder_values[index] if placeholder_values is not None else default_placeholder
            )
        translations[locale] = localized
    return translations


def apply_config_i18n(config_classes: Iterable[Type[PluginConfigBase]]) -> None:
    """把集中维护的多语言元数据注入所有插件配置模型。"""

    for config_class in config_classes:
        class_name = config_class.__name__
        section_texts = _SECTION_TEXTS.get(class_name)
        if section_texts is None:
            raise ValueError(f"配置节缺少 i18n 文案：{class_name}")

        titles, descriptions = section_texts
        config_class.__ui_i18n__ = {
            locale: {
                "title": titles[index],
                "description": descriptions[index],
            }
            for index, locale in enumerate(_LOCALES)
        }

        for field_name, field_info in config_class.model_fields.items():
            json_schema_extra = (
                dict(field_info.json_schema_extra) if isinstance(field_info.json_schema_extra, dict) else {}
            )
            json_schema_extra["i18n"] = _localized_field_entries(
                class_name,
                field_name,
                json_schema_extra,
            )
            field_info.json_schema_extra = json_schema_extra
