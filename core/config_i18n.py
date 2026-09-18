"""插件配置 WebUI Schema 的多语言元数据。"""

from collections.abc import Iterable
from typing import Dict, Tuple, Type

from maibot_sdk import PluginConfigBase


_LOCALES = ("en_US", "ja_JP", "ko_KR")

_SECTION_TEXTS: Dict[str, Tuple[Tuple[str, str, str], Tuple[str, str, str]]] = {
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
    "add_watermark": ("Add Watermark", "ウォーターマークを追加", "워터마크 추가"),
    "admin_user_ids": ("Administrators", "管理者一覧", "관리자 목록"),
    "api_key": ("API Key", "API キー", "API 키"),
    "aspect_ratio": ("Aspect Ratio", "アスペクト比", "화면 비율"),
    "async_poll_interval_seconds": ("Async Poll Interval", "非同期ポーリング間隔", "비동기 폴링 간격"),
    "background": ("Background", "背景", "배경"),
    "base_url": ("Base URL", "ベース URL", "기본 URL"),
    "batch_size": ("Batch Size", "バッチサイズ", "배치 크기"),
    "bypass_china_providers": (
        "Bypass Proxy for China Providers",
        "中国プロバイダーはプロキシを回避",
        "중국 제공자 프록시 우회",
    ),
    "command_reply_mode": ("Command Reply Mode", "コマンド応答モード", "명령 응답 모드"),
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
    "negative_prompt": ("Negative Prompt", "ネガティブプロンプト", "네거티브 프롬프트"),
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
    "width": ("Width", "幅", "너비"),
    "zimage_extra_parameters": ("Z-Image Extra Parameters", "Z-Image 追加パラメータ", "Z-Image 추가 매개변수"),
    "zimage_prompt_extend": ("Z-Image Prompt Expansion", "Z-Image プロンプト拡張", "Z-Image 프롬프트 확장"),
}

_FIELD_LABEL_OVERRIDES: Dict[str, Tuple[str, str, str]] = {
    "PluginSectionConfig.enabled": ("Enable Plugin", "プラグインを有効化", "플러그인 활성화"),
    "StylePresetConfig.enabled": ("Enable Preset", "プリセットを有効化", "프리셋 활성화"),
    "ProxyConfig.enabled": ("Enable Global Proxy", "共通プロキシを有効化", "전역 프록시 활성화"),
    "OpenAICompatibleInstanceConfig.enabled": ("Enable Instance", "インスタンスを有効化", "인스턴스 활성화"),
    "OpenAIModelConfig.enabled": ("Enable OpenAI Platform", "OpenAI プラットフォームを有効化", "OpenAI 플랫폼 활성화"),
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
    "VolcengineModelConfig.api_key": ("Volcengine API Key", "Volcengine API キー", "Volcengine API 키"),
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
            if locale == "en_US":
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
