from sqlalchemy.orm import Session
from app.db import models

def seed_style_presets(db: Session):
    presets = [
        {
            "name": "国风仙侠 · 写实",
            "engine_hint": "本项目使用 Qwen Image / Wan2.2 图像模型",
            "style_pos": """国风仙侠题材，偏写实风格，整体画面真实自然，
人物比例符合真实人体结构，皮肤质感自然，
古风服饰具有真实布料纹理，颜色克制不浮夸，
光影柔和真实，画面统一稳定，非卡通、非动漫风，
整体风格严肃、耐看、偏影视感。""",
            "style_neg": """二次元风格，卡通比例，Q版人物，动漫渲染，
塑料皮肤，过度磨皮，厚涂插画感，
色彩过饱和，滤镜感强，AI感明显，
低清晰度，脸部模糊，畸形肢体，水印，文字。""",
            "llm_style_guard": """无论人物或场景描述中出现任何风格词
（如：卡通、动漫、Q版、二次元等），
都必须被忽略。
你只能在“国风仙侠·写实”这一画风框架内扩写细节，
不得改变整体美术风格。"""
        },
        {
            "name": "国风武侠 · 影视写实",
            "engine_hint": "本项目使用 Qwen Image / Wan2.2 图像模型",
            "style_pos": """中国传统武侠题材，影视级写实风格，
人物比例真实克制，体态自然，
服装为写实武侠古装，布料与皮革材质清晰，
整体画面偏电影镜头感，光影自然稳重，
非卡通、非动漫、非插画风格。""",
            "style_neg": """动漫风格，卡通比例，Q版人物，
游戏建模感，塑料质感，
色彩过饱和，滤镜感强，
AI感明显，低清晰度，水印，文字。""",
            "llm_style_guard": """禁止任何动漫、卡通、二次元倾向，
只能在国风武侠影视写实风格下扩写细节，
不得改变整体画风。"""
        },
        {
            "name": "历史正剧 · 古代写实",
            "engine_hint": "本项目使用 Qwen Image / Wan2.2 图像模型",
            "style_pos": """中国古代历史正剧风格，极度写实，
人物造型严谨克制，比例真实，
服装考究，符合历史质感，
色彩低饱和，画面稳重严肃，
整体接近历史电视剧或纪录片质感。""",
            "style_neg": """仙侠风格，奇幻元素，
动漫、卡通、插画风，
过度美化，夸张光效，
AI感明显，水印，文字。""",
            "llm_style_guard": """禁止仙侠、奇幻、动漫、卡通等元素，
只能在历史正剧写实风格下扩写。"""
        },
        {
            "name": "现代写实 · 摄影风",
            "engine_hint": "本项目使用 Qwen Image / Wan2.2 图像模型",
            "style_pos": """现代现实题材，摄影级写实风格，
人物比例真实，皮肤细节自然，
光影接近真实摄影，构图简洁，
整体画面干净、自然、克制。""",
            "style_neg": """动漫风格，卡通比例，
插画感，厚涂风格，
过度磨皮，虚假光效，
AI痕迹明显，水印，文字。""",
            "llm_style_guard": """禁止动漫、插画、卡通倾向，
只允许现代摄影写实风格。"""
        },
        {
            "name": "科幻电影 · 写实",
            "engine_hint": "本项目使用 Qwen Image / Wan2.2 图像模型",
            "style_pos": """科幻题材，电影级写实风格，
人物与环境具有真实材质与物理光照，
色调偏冷，结构合理，
整体画面具有科幻电影镜头感。""",
            "style_neg": """卡通风格，动漫风格，
Q版比例，低模游戏感，
塑料材质，AI感明显。""",
            "llm_style_guard": """禁止动漫或卡通科幻，
只能在写实科幻电影风格下扩写。"""
        },
        {
            "name": "赛博朋克 · 写实",
            "engine_hint": "本项目使用 Qwen Image / Wan2.2 图像模型",
            "style_pos": """赛博朋克题材，偏写实电影风格，
未来都市氛围，霓虹光影，
人物比例真实，材质细节清晰，
整体画面偏暗色调，科技感强。""",
            "style_neg": """动漫赛博风，卡通比例，
插画感强，色彩失控，
低清晰度，AI痕迹明显。""",
            "llm_style_guard": """禁止动漫化赛博朋克，
只允许写实电影级赛博风格。"""
        },
        {
            "name": "暗黑奇幻 · 写实",
            "engine_hint": "本项目使用 Qwen Image / Wan2.2 图像模型",
            "style_pos": """暗黑奇幻题材，写实风格，
整体色调偏暗，气氛凝重，
人物比例真实，细节克制，
整体接近暗黑电影视觉风格。""",
            "style_neg": """动漫奇幻，卡通暗黑风，
Q版比例，插画感，
夸张造型，AI感明显。""",
            "llm_style_guard": """禁止动漫或卡通奇幻，
只能在暗黑奇幻写实风格下扩写。"""
        },
        {
            "name": "末世废土 · 写实",
            "engine_hint": "本项目使用 Qwen Image / Wan2.2 图像模型",
            "style_pos": """末世废土题材，写实电影风格，
环境破败真实，质感粗粝，
人物造型现实克制，
整体画面偏灰暗，末日电影视觉。""",
            "style_neg": """卡通废土，动漫末世，
游戏贴图感，塑料材质，
AI痕迹明显，水印，文字。""",
            "llm_style_guard": """禁止动漫或卡通末世风格，
只允许写实废土电影风格。"""
        }
    ]

    for data in presets:
        existing = db.query(models.StylePreset).filter(models.StylePreset.name == data["name"]).first()
        if not existing:
            preset = models.StylePreset(**data)
            db.add(preset)
        else:
            # Update existing?
            existing.engine_hint = data["engine_hint"]
            existing.style_pos = data["style_pos"]
            existing.style_neg = data["style_neg"]
            existing.llm_style_guard = data["llm_style_guard"]
            
    db.commit()

def seed_llm_profiles(db: Session):
    # Check if any profile exists
    count = db.query(models.LLMProfile).count()
    if count > 0:
        return

    # If empty, migrate from env
    from app.config import config
    
    # Default to DeepSeek logic if config has values
    # Or just check if OPENAI_API_KEY is present
    api_key = config.OPENAI_API_KEY
    if api_key:
        print("Seeding default LLM Profile from environment variables...")
        base_url = config.OPENAI_BASE_URL
        if not base_url:
            base_url = "https://api.deepseek.com" # Default fallback
            
        model = config.LLM_MODEL
        if not model:
            model = "deepseek-chat"
            
        profile = models.LLMProfile(
            name="DeepSeek-Default",
            provider="deepseek",
            base_url=base_url,
            api_key=api_key,
            model=model,
            is_default=True
        )
        db.add(profile)
        db.commit()
    else:
        # Create a dummy or skip?
        # User requirement: "若未选择则默认 DeepSeek"
        # But if no API key, we can't really do much. 
        # Let's create a placeholder if user wants?
        # Better to leave empty so user is forced to configure UI or env.
        pass
