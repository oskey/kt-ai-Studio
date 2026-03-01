import json
import re
import os
from openai import OpenAI
from app.config import config

def clean_player_desc(desc: str, name: str) -> str:
    """
    Cleans the player_desc string by removing names and utility phrases.
    """
    if not desc:
        return ""
        
    # 1. Remove name patterns at the start
    # Regex for "^Name is/was/:/," etc.
    # We use re.IGNORECASE just in case
    name_patterns = [
        rf"^{re.escape(name)}\s*是",
        rf"^{re.escape(name)}\s*为",
        rf"^{re.escape(name)}\s*：",
        rf"^{re.escape(name)}\s*:",
        rf"^{re.escape(name)}\s*，",
        rf"^{re.escape(name)}\s*,",
        rf"^{re.escape(name)}\s*（",
        rf"^{re.escape(name)}\s*\(",
        rf"^{re.escape(name)}", # Fallback: just the name at start
    ]
    
    for pattern in name_patterns:
        desc = re.sub(pattern, "", desc, flags=re.IGNORECASE).strip()
        
    # 2. Split into sentences and filter utility phrases
    # Split by common delimiters: 。 ； ; \n AND commas ， ,
    # This prevents long comma-separated lists from being deleted entirely if one part has a keyword.
    sentences = re.split(r'(?<=[。；;\n，,])', desc)
    cleaned_sentences = []
    
    forbidden_keywords = [
        "用途", "合成", "视频", "映射", "后续", "适合", "用于", "方便", 
        "场景融合", "图生视频", "角色一致性", "建议", "可以"
    ]
    
    for sent in sentences:
        if not sent.strip():
            continue
        # Check if sentence contains any forbidden keyword
        if any(kw in sent for kw in forbidden_keywords):
            continue
        cleaned_sentences.append(sent)
        
    cleaned_desc = "".join(cleaned_sentences).strip()
    
    # 3. Final cleanup (remove leading/trailing punctuation)
    cleaned_desc = re.sub(r"^[，,：:。.；;]", "", cleaned_desc).strip()
    cleaned_desc = re.sub(r"[，,：:；;]$", "。", cleaned_desc).strip() # End with period if comma left
    
    return cleaned_desc

from app.db import models

def normalize_negative_prompt(raw_neg: str) -> str:
    """
    Ensures negative prompt contains mandatory safety tags for Qwen/Wan2.2.
    """
    if not raw_neg:
        raw_neg = ""
        
    mandatory_negatives = [
        "赤脚", "脚部缺失", "下半身裁切", "腿部模糊", "脚被遮挡",
        "坐姿", "蹲姿", "倚靠", "道具遮挡身体", "多人画面"
    ]
    
    # Simple check and append
    # Normalize punctuation for checking
    check_str = raw_neg.replace("，", ",").replace("\n", ",")
    
    final_parts = [raw_neg]
    
    for tag in mandatory_negatives:
        if tag not in check_str:
            final_parts.append(tag)
            
    return "，".join(final_parts).strip("，")

def normalize_prompt_structure(raw_text: str, style_name: str) -> str:
    """
    Parses the raw prompt_pos from LLM (which should contain tags like 【人物外观】)
    and reassembles it into the fixed structure.
    """
    if not raw_text:
        return ""

    # 1. Define Sections
    sections = {
        "appearance": [],
        "body_pose": [],
        "clothing": [],
        "quality": []
    }
    
    # 2. Hard Constraints (Always present)
    core_constraints = [
        f"<{style_name}>",
        "单人画面",
        "站立姿态",
        "正面或接近正面视角",
        "人物垂直居中构图",
        "全身像",
        "纯白色背景", # Updated to Pure White Background
        "Simple Background", # English reinforcement
        "White Background",  # English reinforcement
        "无遮挡，无道具遮挡身体",
        "人物完整不裁切",
        "下半身完整可见",
        "脚部完整可见，必须穿鞋（不可赤脚）"
    ]
    
    # 3. Parse Raw Text
    # Strategy: Split by "【...】" tags
    # Example raw:
    # 【人物外观】
    # ...
    # 【体型与姿态】
    # ...
    
    # Normalize newlines
    raw_text = raw_text.replace("\r\n", "\n")
    lines = raw_text.split('\n')
    
    current_section = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check tags
        if "人物外观" in line and ("【" in line or "[" in line):
            current_section = "appearance"
            continue
        elif ("体型" in line or "姿态" in line) and ("【" in line or "[" in line):
            current_section = "body_pose"
            continue
        elif "服装" in line and ("【" in line or "[" in line):
            current_section = "clothing"
            continue
        elif ("画面" in line or "质感" in line or "清晰度" in line) and ("【" in line or "[" in line):
            current_section = "quality"
            continue
            
        # If line matches hard constraints, ignore (we inject them manually)
        if any(c.replace("，", "").replace(",", "") in line.replace("，", "").replace(",", "") for c in core_constraints if "style" not in c):
            continue
            
        if current_section:
            sections[current_section].append(line)
        else:
            # Content before first tag? Or LLM failed to use tags?
            # Put in appearance as fallback
            sections["appearance"].append(line)

    # 4. Reassemble
    final_parts = []
    
    # 【核心约束】
    final_parts.append("【核心约束】")
    final_parts.extend(core_constraints)
    final_parts.append("") # Empty line
    
    # 【人物外观】
    if sections["appearance"]:
        final_parts.append("【人物外观】")
        final_parts.extend(sections["appearance"])
        final_parts.append("")

    # 【体型与姿态】
    if sections["body_pose"]:
        final_parts.append("【体型与姿态】")
        final_parts.extend(sections["body_pose"])
        final_parts.append("")
        
    # 【服装】
    if sections["clothing"]:
        final_parts.append("【服装】")
        final_parts.extend(sections["clothing"])
        final_parts.append("")
        
    # 【画面与质感】
    if sections["quality"]:
        final_parts.append("【画面与质感】")
        final_parts.extend(sections["quality"])
        
    return "\n".join(final_parts).strip()

def normalize_scene_prompt_structure(raw_text: str, style_name: str, style_pos: str) -> str:
    """
    Parses the raw prompt_pos from LLM for SCENE and reassembles it into the fixed structure.
    """
    if not raw_text:
        return ""

    # 1. Define Sections
    sections = {
        "shot_type": [],
        "structure": [],
        "materials": [],
        "lighting": [],
        "quality": []
    }
    
    # 2. Hard Constraints (Always present)
    # 必须包含 style_pos 的关键信息
    # 纯场景画面, 无人物无角色, 无动物, 无文字无logo, 空间结构清晰, 画面稳定, 背景完整不裁切, 高一致性，可复用为多镜头场景底图
    core_constraints = [
        f"<{style_name}>",
        style_pos,
        "纯场景画面",
        "无人物无角色",
        "无动物",
        "无文字无logo",
        "空间结构清晰",
        "画面稳定",
        "背景完整不裁切",
        "高一致性，可复用为多镜头场景底图"
    ]
    
    # 3. Parse Raw Text
    # Strategy: Split by "【...】" tags
    raw_text = raw_text.replace("\r\n", "\n")
    lines = raw_text.split('\n')
    
    current_section = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check tags
        if "镜头" in line and ("【" in line or "[" in line):
            current_section = "shot_type"
            continue
        elif "场景结构" in line and ("【" in line or "[" in line):
            current_section = "structure"
            continue
        elif ("材质" in line or "固定元素" in line) and ("【" in line or "[" in line):
            current_section = "materials"
            continue
        elif ("光影" in line or "环境" in line) and ("【" in line or "[" in line):
            current_section = "lighting"
            continue
        elif ("画面" in line or "质感" in line) and ("【" in line or "[" in line):
            current_section = "quality"
            continue
            
        # If line matches hard constraints, ignore
        if any(c.replace("，", "").replace(",", "") in line.replace("，", "").replace(",", "") for c in core_constraints if "style" not in c and len(c) > 2):
            continue
            
        if current_section:
            sections[current_section].append(line)
        else:
            # Fallback to structure
            sections["structure"].append(line)

    # 4. Reassemble
    final_parts = []
    
    # 【核心约束】
    final_parts.append("【核心约束】")
    final_parts.extend(core_constraints)
    final_parts.append("") 

    # 【镜头景别】
    if sections["shot_type"]:
        final_parts.append("【镜头景别】")
        final_parts.extend(sections["shot_type"])
        final_parts.append("")
    
    # 【场景结构】
    if sections["structure"]:
        final_parts.append("【场景结构】")
        final_parts.extend(sections["structure"])
        final_parts.append("")

    # 【材质与固定元素】
    if sections["materials"]:
        final_parts.append("【材质与固定元素】")
        final_parts.extend(sections["materials"])
        final_parts.append("")
        
    # 【光影与环境】
    if sections["lighting"]:
        final_parts.append("【光影与环境】")
        final_parts.extend(sections["lighting"])
        final_parts.append("")
        
    # 【画面与质感】
    # Default values if empty
    default_quality = ["超清晰", "细节丰富", "真实材质纹理", "干净画面", "低噪点", "无AI涂抹感"]
    
    final_parts.append("【画面与质感】")
    if sections["quality"]:
        final_parts.extend(sections["quality"])
    else:
        final_parts.extend(default_quality)
        
    # Final cleanup: Remove known character-related keywords that might have slipped in from style
    character_keywords = [
        "五官", "眼睛", "发型", "肤色", "皮肤", "手指", "面部", "肢体", "身材", "比例", "头身", "表情", "眼神"
    ]
    cleaned_final_text = "\n".join(final_parts).strip()
    
    # Filter out lines containing character keywords
    lines = cleaned_final_text.split('\n')
    filtered_lines = []
    for line in lines:
        if any(kw in line for kw in character_keywords):
            continue
        filtered_lines.append(line)
        
    return "\n".join(filtered_lines).strip()

def normalize_scene_negative_prompt(raw_neg: str, style_neg: str) -> str:
    """
    Ensures negative prompt contains mandatory safety tags for Scene.
    """
    if not raw_neg:
        raw_neg = ""
        
    # 系统补强neg
    mandatory_negatives = [
        "人物", "角色", "人体", "脸", "手", "眼睛", "皮肤", "肢体", "服装", "人影",
        "动物", "宠物",
        "文字", "水印", "logo", "标志", "字幕",
        "漫画风", "二次元", "动漫", "卡通", "Q版",
        "镜头语言", "特写", "俯拍", "仰拍", "景深", "电影感构图",
        "脏乱", "杂物堆积", "随机小物件", "乱贴纸",
        "低清晰度", "模糊", "噪点", "涂抹感", "变形", "崩坏"
    ]
    
    # Normalize punctuation
    check_str = raw_neg.replace("，", ",").replace("\n", ",")
    
    final_parts = []
    
    # 1. Style Neg
    if style_neg:
        final_parts.append(style_neg)
        
    # 2. LLM Neg
    final_parts.append(raw_neg)
    
    # 3. Mandatory Neg
    for tag in mandatory_negatives:
        if tag not in check_str and tag not in style_neg:
            final_parts.append(tag)
            
    return "，".join(final_parts).strip("，")

def generate_player_prompts(name: str, sex: str, mark: str, style_preset=None, llm_profile=None, optimize_ancient=False) -> dict:
    if not llm_profile:
        raise ValueError("No LLM Profile provided. Please configure LLM in Settings.")

    client = OpenAI(
        api_key=llm_profile.api_key,
        base_url=llm_profile.base_url
    )
    
    # Use profile model or fallback
    model_name = llm_profile.model or "gpt-3.5-turbo"
    
    style_name = style_preset.name if style_preset else "默认通用风格"
    style_guard = style_preset.llm_style_guard if style_preset else "无特殊风格约束，保持写实。"
    style_pos = style_preset.style_pos if style_preset else ""
    style_neg = style_preset.style_neg if style_preset else ""
    # Add engine hint for model-specific prompting
    engine_hint = f"{style_preset.engine_hint}" if style_preset and style_preset.engine_hint else "本项目使用 Qwen Image / Wan2.2 图像模型"
    
    optimize_prompt = ""
    if optimize_ancient and str(sex).lower() in ["female", "女", "女性"]:
         optimize_prompt = """
    【古装类服装优化规则 (CRITICAL)】
    - 针对女性角色：
      - **必须强调曲线美**：使用 "hourglass figure", "curvy body", "slim waist", "wide hips" 等词汇。
      - **服装设计 (重要)**：
        - 如果是女性角色：
          - **上身设计**：**必须包含内搭描述**，如抹胸(tube top)、肚兜(dudou)、束胸(corset)等。**必须显露乳沟** (cleavage, deep v-neck)，展现丰满身材。
          - **下身设计 (美腿优化)**：
            - **极高开叉/侧边镂空**：如果是旗袍或长裙，必须强调 **“单侧极高开叉直至腰部 (single ultra-high slit up to the waist)”** 或 **“单侧完全镂空 (one-side cutout)”**。**严禁双侧开叉**。
            - **视觉效果**：明确描述 **“从开叉侧可以看到完整的臀部曲线 (full side hip visible through the slit)”**，**“大腿根部若隐若现 (upper thigh exposed)”**，**“可以看到少量内裤边缘 (panties slightly visible through the slit)”**。
            - **无内搭/隐形内搭**：**下身禁止描述任何可见的内搭裤、打底裤或衬裙** (no leggings, no underskirt)，以实现“大腿完全裸露”的效果。
            - **关键约束**：虽然要求极其性感的大胆剪裁，但仍需保持基本的遮挡，**“关键部位被衣物遮挡 (privates covered)”**，营造一种“危险的性感”和“极致的诱惑”。
          - **材质要求**：使用 "translucent silk", "chiffon", "lace", "sheer fabric" 等能体现若隐若现效果的材质。
          - **具体示例**："wearing a cheongsam with a single ultra-high slit revealing the entire leg and side hip", "one-side cutout dress showing panties slightly", "translucent fabric draping over bare legs".
        - 目的：最大程度展现女性的修长美腿和臀部曲线，通过单侧极高开叉和侧边镂空设计，营造极致性感、若隐若现的视觉冲击力。
         """

    system_prompt = f"""你是一个【图像生成提示词扩写器】。
    当前项目已锁定画风，这是最高优先级约束。

    画风名称：{style_name}

    【核心画风提示词】（必须严格遵守，权重最高）：
    Positive (正面风格): {style_pos}
    Negative (负面风格): {style_neg}

    【画风执行守则】（LLM Style Guard）：
    {style_guard}

    【下游生成模型，你输出的提示词必须可直接用于这个 Comfyui 模型】
    {engine_hint}

    【任务目标】
    你需要生成一张用于后续场景合成的【人物素材基图】。
    这张图必须是“干净的、去背景的、高质量的人物立绘”。
    【比例与背景判定规则（CRITICAL · 判错级别）】
    - 人物必须为明显长腿比例，头身比例 ≥ 8.5 头身。
    - 必须明确写出：上身较短（short torso）+ 下身明显更长（long legs）。
    - 如果是女性：腿一定要细，加入细长的描述。
    - 若描述中出现或隐含“五五身 / 上下身等长 / 腿短”，视为错误输出。
    - 若未明确写出身高（Height: XXX cm），视为错误输出。
    
    {optimize_prompt}

    【纯白背景硬性规则（CRITICAL）】
    - 背景必须为：Pure White Background。
    - 禁止出现：地面、阴影、投影、渐变、纹理、空间感、环境光。
    - 若出现任何背景元素，视为错误输出。

    你的任务：
    1) 仅在该画风下扩写人物细节（外观、服装、发型等）。
    2) **背景控制 (CRITICAL)**：无论画风如何，生成的图片**必须是纯色背景（Pure White Background）**。禁止生成任何环境、光影背景、复杂的场景元素。
       - 原因：这张图后续会被抠图，背景越干净越好。
       - 画风提示词仅用于控制人物本身的绘画风格（如笔触、上色、光影），**绝对不要**把画风中的场景描述（如“室内”、“街道”、“森林”）带入到这张图中。
    3) 输出必须详细，适合图像模型理解。
    4) 不要出现人物名字。
    5) 所有输出内容【只能使用中文】。
    6) 输出格式【必须是合法 JSON】。

    你生成的描述将被系统整理为以下结构：
    - 人物外观
    - 体型与姿态
    - 服装
    - 画面与质感

    请尽量使用可拆分的短句或多行描述，避免长段总结性文本。
    对于 prompt_pos 字段，请务必按以下【标签格式】分段输出内容：

    【人物外观】
    (这里写外观描述...)

    【体型与姿态】
    (这里写体型动作...)

    【服装】
    (这里写服装...)

    【画面与质感】
    (这里写画质光影...)
    """
    
    user_prompt = f"""
    人物基础描述：
    {mark}
    (姓名：{name}，性别：{sex})
    
    生成要求：
    - 人物基图
    - 全身像
    - **纯白背景 (Pure White Background)**，无任何杂物
    - 基础服装（用于后续换装）
    - **身材比例 (CRITICAL)**：
      - 必须在 Prompt 中包含明确的身材比例描述。
      - 例如：8头身(8 heads tall), 长腿(long legs), 上身较短(short torso)。
      - 比例描述必须具备“强对比”：
      - 明确指出：下身长度明显长于上身（not equal）。
      - 禁止模糊描述（如“比例协调”“正常身材”）。
      - 如果是怪物或非人生物，描述其特殊的肢体比例（如：巨大的上肢，短小的下肢）。
      - 必须包含身高描述 (Height: X cm)。
    
    请输出 JSON：
    {{
      "prompt_pos": "严格按照 System Prompt 中的【标签格式】输出，包含：人物外观、体型与姿态、服装、画面与质感。必须包含：全身图、纯白背景、身材比例描述、身高描述",
      "prompt_neg": "避免画风漂移、比例错误、低质量、半身、裁切、复杂背景、环境背景、五五身(equal torso and legs)",
      "player_desc": "只包含人物客观外观特征，不含名字、不含用途说明"
    }}
    """

    # --- Debug Logging Start ---
    if config.LLM_LOG:
        print("\\n" + "="*50)
        print(f" [LLM Request] Provider: {llm_profile.provider} | Model: {model_name}")
        print("-" * 20 + " System Prompt " + "-" * 20)
        print(system_prompt.strip())
        print("-" * 20 + " User Prompt " + "-" * 20)
        print(user_prompt.strip())
        print("="*50 + "\\n")
    # --- Debug Logging End ---

    try:
        is_doubao = "volces.com" in llm_profile.base_url or "doubao" in model_name.lower()
        
        # Prepare params
        params = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "timeout": 120
        }
        
        # Only add response_format if NOT Doubao (as it might not support it or requires strict json mode)
        # Actually Doubao supports it but let's be safe. If user says it's not standard.
        if not is_doubao:
            params["response_format"] = {"type": "json_object"}
            
        response = client.chat.completions.create(**params)
        
        content = response.choices[0].message.content
        
        # --- Debug Logging Start ---
        if config.LLM_LOG:
            print("\\n" + "="*50)
            print(" [LLM Response]")
            print("-" * 20 + " Raw Content " + "-" * 20)
            print(content)
            print("="*50 + "\\n")
        # --- Debug Logging End ---
        
        usage = response.usage.model_dump() if response.usage else {}
        
        result = {}
        # Robust JSON extraction
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
            if match:
                result = json.loads(match.group(1))
            else:
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    result = json.loads(match.group(0))
                else:
                    # Retry logic for non-JSON? 
                    # User requirement: "如果模型返回非 JSON：做一次“修复重试”"
                    print(" [Warning] JSON Parse Failed. Attempting repair retry...")
                    
                    repair_prompt = "上一次输出不是合法的 JSON 格式。请修正格式，只输出纯 JSON，不要包含 Markdown 代码块或其他文字。"
                    
                    repair_resp = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                            {"role": "assistant", "content": content},
                            {"role": "user", "content": repair_prompt}
                        ],
                        response_format={"type": "json_object"}
                    )
                    repair_content = repair_resp.choices[0].message.content
                    print(f" [LLM Repair Response] {repair_content}")
                    
                    try:
                        match = re.search(r'\{.*\}', repair_content, re.DOTALL)
                        if match:
                            result = json.loads(match.group(0))
                        else:
                            raise ValueError(f"无法解析 LLM 返回的 JSON (重试后): {repair_content}")
                    except:
                         raise ValueError(f"无法解析 LLM 返回的 JSON: {content}")

        
        # Merge usage info
        result["_usage"] = usage
        
        # --- Post-processing / Cleaning ---
        if "player_desc" in result:
            original_desc = result["player_desc"]
            cleaned_desc = clean_player_desc(original_desc, name)
            
            # Validation: Check length (<10 words retry logic)
            if len(cleaned_desc) < 10:
                print(f" [Warning] Cleaned desc too short: {cleaned_desc}. Retrying with refinement...")
                
                # Retry Request
                retry_user_prompt = f"""
                上一次生成的描述太短（"{cleaned_desc}"）。
                请在不改变画风（{style_name}）的前提下，进一步细化外观与服装细节。
                
                要求：
                - 长度 30~100 字
                - 只描述外观特征
                - 不要解释用途
                """
                
                retry_resp = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": retry_user_prompt}
                    ],
                    response_format={"type": "json_object"}
                )
                
                retry_content = retry_resp.choices[0].message.content
                print(f" [LLM Retry Response] {retry_content}")
                
                try:
                    retry_result = json.loads(retry_content)
                    if "player_desc" in retry_result:
                        cleaned_desc = clean_player_desc(retry_result["player_desc"], name)
                        result["player_desc"] = cleaned_desc
                        # Also update prompts if retry improved them
                        if "prompt_pos" in retry_result:
                            result["prompt_pos"] = retry_result["prompt_pos"]
                        if "prompt_neg" in retry_result:
                            result["prompt_neg"] = retry_result["prompt_neg"]
                except:
                    print("Failed to parse retry response, keeping original.")

            result["player_desc"] = cleaned_desc
            print(f" [Final Cleaned Desc] {cleaned_desc}")

        # --- Normalize Prompt Structure ---
        if "prompt_pos" in result:
            raw_pos = result["prompt_pos"]
            normalized_pos = normalize_prompt_structure(raw_pos, style_name)
            result["prompt_pos"] = normalized_pos
            print(f" [Normalized Prompt] \\n{normalized_pos}")

        # --- Normalize Negative Prompt ---
        if "prompt_neg" in result:
            raw_neg = result["prompt_neg"]
            normalized_neg = normalize_negative_prompt(raw_neg)
            result["prompt_neg"] = normalized_neg
            print(f" [Normalized Neg Prompt] {normalized_neg}")

        return result
            
    except Exception as e:
        raise Exception(f"OpenAI API Error ({llm_profile.provider}): {str(e)}")

def generate_video_prompts(
    video_context: str,
    style_preset=None,
    llm_profile=None,
    video_model="wan2.2"
) -> dict:
    """
    Generate prompts for Image-to-Video generation based on scene context.
    video_context: JSON string containing 'scene' and 'characters' info.
    """
    if not llm_profile:
        raise ValueError("No LLM Profile provided.")

    client = OpenAI(
        api_key=llm_profile.api_key,
        base_url=llm_profile.base_url
    )

    engine_hint = f"{style_preset.engine_hint}" if style_preset and style_preset.engine_hint else "本项目使用 Qwen Image / Wan2.2 图像模型"
    
    style_name = style_preset.name if style_preset else "默认通用风格"
    style_guard = style_preset.llm_style_guard if style_preset else "无特殊风格约束，保持写实。"
    style_pos = style_preset.style_pos if style_preset else ""
    style_neg = style_preset.style_neg if style_preset else ""
    
    # Ensure model_name is defined before use
    model_name = llm_profile.model or "gpt-3.5-turbo"

    # Dialogues Context Logic
    dialogues_constraint = ""
    raw_dialogues = None

    try:
        # Check if video_context is string or dict
        if isinstance(video_context, str):
            ctx = json.loads(video_context)
        else:
            ctx = video_context

        if "scene" in ctx and "dialogues" in ctx["scene"]:
            raw_dialogues = ctx["scene"]["dialogues"]
    except Exception as e:
        print(f"Failed to parse video_context: {e}")
        pass

    # Direct Length Check & String Extraction
    has_dialogue = False
    d_text = ""

    if raw_dialogues:
        # Case 1: List (most common)
        if isinstance(raw_dialogues, list):
            if len(raw_dialogues) > 0:
                has_dialogue = True
                # Try to format list of dicts
                try:
                    lines = []
                    for d in raw_dialogues:
                        if isinstance(d, dict):
                            lines.append(f"- {d.get('role', 'Unknown')}: {d.get('content', '')}")
                        else:
                            lines.append(f"- {str(d)}")
                    d_text = "\n".join(lines)
                except:
                    # Fallback: just dump the list structure
                    d_text = json.dumps(raw_dialogues, ensure_ascii=False)
        
        # Case 2: String (serialized JSON or raw text)
        elif isinstance(raw_dialogues, str):
            if len(raw_dialogues.strip()) > 2: # "[]" is length 2, so >2 implies content
                has_dialogue = True
                d_text = raw_dialogues # Use directly

    # LTX Audio Logic
    ltx_audio_instruction = ""
    is_ltx = video_model in ["ltx2", "ltx2_lora"]
    
    if is_ltx and has_dialogue:
        ltx_audio_instruction = """
    6. **LTX模型音频生成指令 (CRITICAL FOR LTX)**：
       - 当前使用的是支持音频生成的 LTX 模型。
       - **必须在提示词中明确包含人物所说的话**。
       - 格式要求：在描述完人物动作后，追加句式：`The character says: "[对话内容]"`。
       - **示例**：
         - 原句："你好，请问这里是客栈吗？"
         - 提示词："The young man waves his hand and says: 'Hello, is this the inn?'"
       - 请务必将对话内容翻译为中文,考虑到通用性，请**直接使用中文**。
       - **建议策略**：为了保险起见，请输出：`The character is saying: "[对话内容]"`。
       - **情绪与口型强化 (必须包含)**：
         - 结合对话内容，从以下词汇中选择符合情绪的词加入 Prompt：
         - speaking visibly, talking with mouth opening, lips moving clearly
         - shouting loudly (如果激动/愤怒)
         - whispering with lip movement (如果低语/秘密)
         - crying and speaking (如果悲伤)
         - laughing and talking (如果开心)
       """

    if has_dialogue:
        # Non-LTX Lip Sync Simulation Logic
        extra_lip_sync = ""
        if not is_ltx:
            extra_lip_sync = """
       - **口型模拟 (Lip Sync Simulation) - CRITICAL**：
         - 虽然当前模型不生成音频，但为了让画面中的口型逼真，**必须**在提示词中包含详细的口型描述。
         - **必须包含**：描述人物说话时的具体神态、嘴部幅度和面部肌肉变化。
         - **核心句式**：
           - `The character is clearly speaking: "[对话内容]"`
           - `Mouth moving naturally to say: "[对话内容]"`
         - **强化描述**：
           - "lips articulating clearly" (嘴唇清晰咬字)
           - "mouth opening and closing in rhythm" (嘴部有节奏开合)
           - "facial muscles moving while talking" (说话时面部肌肉牵动)
           - "jaw moving up and down" (下颚上下运动)
         - **情绪结合**：
           - 如果是愤怒："shouting with wide open mouth, veins visible on neck"
           - 如果是悲伤："trembling lips, speaking with tears"
           - 如果是平静："calmly speaking, subtle mouth movement"
            """

        dialogues_constraint = f"""
    【对话动作引导 (重要)】
    本场景包含以下人物对话：
    {d_text}
    
    任务要求：
    1. 你必须理解对话的情绪与内容，在 prompt_pos 中描述对应人物正在说话的状态。
    2. **强制开口暗示 (CRITICAL)**：
       - 如果人物在说话，必须在 Prompt 中包含明确且强烈的“嘴部动态”描述。
       - **必选词汇 (必须包含至少一个)**：speaking visibly, talking with mouth opening, lips moving clearly, shouting loudly (如果激动), whispering with lip movement (如果低语)。
       - **时长控制**：根据对白长度（字数）来调整嘴部动作的持续感。
         - 短句（<5字）："quick lip movement", "short phrase speaking"
         - 长句（>10字）："continuous speaking", "sustained mouth movement", "long conversation"
       - **示例**："The young man is speaking continuously, mouth opening and closing clearly", "lips moving naturally and visibly as she talks"。
       - **严禁闭嘴**：绝对禁止 "mouth closed", "silent" 等描述出现在说话角色的 Prompt 中。
       {extra_lip_sync}
    3. **角色对应 (Crucial)**：
       - 请根据 `characters` 列表中的 `name` 与对话中的 `role` 进行匹配。
       - 必须明确指出**哪个人物**在说话。例如："The young man (陈平安) is talking..." 或 "The shopkeeper (陶掌柜) is speaking..."。
       - 如果有多人对话，请描述他们的交互状态（如：面对面交谈、一人倾听一人诉说）。
    4. **核心红线 (字幕屏蔽 - 极重要)**：
       - **CRITICAL**: 绝对禁止在画面底部生成任何形式的字幕、台词、文字、气泡。
       - 模型非常容易将对话内容渲染为文字，必须在 prompt_neg 中强力压制。
       - **正向提示词中也必须追加**：`no subtitles, no text on screen`。
       - 在描述说话时，侧重于“动作”而非“内容展示”。
    5. 描述“人物说话的动作与神态”。
    """
    else:
        dialogues_constraint = """
    【无对话场景】
    本场景无对话。请描述人物处于闭嘴、静默或专注于动作的状态。
    """

    video_context_str = video_context if isinstance(video_context, str) else json.dumps(video_context, ensure_ascii=False, indent=2)

    system_prompt = f"""你是一个专业的【图生视频提示词生成器】。
    你的任务是根据提供的【场景与角色上下文】，为 下游生成模型 视频生成模型编写提示词。

    【项目画风】
    {style_name}
    {style_guard}

    【画风正向（必须融入）】
    {style_pos}

    【画风反向（必须融入）】
    {style_neg}

    【下游生成模型，你输出的提示词必须可直接用于这个 Comfyui 模型】
    {engine_hint}

    【输入数据说明】
    输入是一个 JSON，包含 `scene`（场景信息）和 `characters`（角色列表）。
    `characters` 数组中的 `action_desc` 描述了角色在画面中的位置（如"左侧前景"）和动作。
    注意：ComfyUI 无法识别角色名字（如"陈平安"），也无法区分 image1/image2。
    
    如果 `scene` 中包含 `dialogues` 字段，说明本场景有角色对话。你必须参考这些对话来设计人物的动作（如开口说话、表情变化）。

    【任务要求】
    1. **生成正向提示词 (prompt_pos)**：
       - 必须是一段流畅的中文描述。
       - **核心任务**：将 `characters` 中的空间位置和动作描述，转化为模型能理解的全局画面描述。
       - **去名化**：绝对禁止出现角色名字。用 "a young man", "a woman in red", "a figure" 等通用词代替。
       - **空间引导**：明确描述人物在画面中的位置（e.g., "on the left foreground", "in the center", "walking away from camera"）。
       - **融合环境**：结合 `scene` 的 `visual_desc` 和 `shot_type`，描述整体氛围、光影和动态。
       - **风格保持**：必须融入【画风正向】提示词，确保视频风格与原图一致。
       - **对话动作**：如果存在对话，描述人物说话的神态动作，但**严禁生成字幕**。
       
       - **字幕屏蔽强化 (No Subtitles - CRITICAL)**：
         - 在 Prompt 结尾，**必须追加**以下英文负面指令：
         - `no subtitles, no subtitles, no on-screen text, no speech bubble`
         - 虽然通常负面词放在 prompt_neg，但为了对抗模型强烈的加字幕倾向，**正向 Prompt 中也要显式声明“不要字幕”**。
       
       - **环境与动作强化 (Scene & Action Enrichment - CRITICAL)**：
         - **环境动态化**：不要只描述静态背景。根据场景类型（室内/室外/特殊），自动添加合理的环境动态。
           - 示例（室外）："wind blowing through hair/clothes", "leaves falling", "dust floating in light rays", "clouds moving slowly".
           - 示例（室内）："candle light flickering", "curtains swaying gently", "dust motes dancing in the light".
           - **特殊情况（系统空间/纯色背景）**：如果是 Pure Black/White Background，**不要添加自然环境动态**（无风、无落叶）。专注于人物的微动作或简单的光影流动（"subtle lighting shift", "rim light moving"）。
         - **人物微动作**：除了主要动作（如说话、行走），添加自然的微小肢体语言，避免人物僵硬。
           - 示例："blinking naturally", "slight head tilt", "hand gestures while speaking", "shifting weight", "breathing movement".
         - **光影互动**：描述人物与环境光影的交互。
           - 示例："light reflecting on face", "shadows moving across the body", "rim light highlighting the silhouette".
         - **目的**：让视频画面充满生机和细节，打破“静态图+嘴动”的僵硬感。

    2. **生成负向提示词 (prompt_neg)**：
       - 必须包含【画风反向】提示词。
       - 包含通用视频负向词（如 "static, distortion, morphing, watermarks, text, bad anatomy"）。
       - **强制包含 (字幕屏蔽 - CRITICAL)**：
         - 必须在 Negative Prompt 中包含以下核心词汇（建议保留英文）：
         - "subtitles, speech bubble, text, caption, lower third, lyrics, screen text, dialogue box, typography, chinese characters, english text, watermark"
         - 这些词汇对于防止模型将对话内容渲染为字幕至关重要。
       - 返回的提示词建议使用中文描述画面内容，但技术性负面词可保留英文。

    3. **生成视频参数 (fps, length)**：
       - **智能时长计算**：
         - 默认推荐时长：5秒。
         - **自动延时**：如果剧情动作复杂或对白较长（>15字），5秒无法完整展示，请适当增加时长。
         - **时长上限**：绝对不超过 10秒（HARD LIMIT）。
         - 优先尝试在 5秒内完成叙事；仅在必要时扩展至 6-10秒。
       - **FPS 推荐**：
         - 默认：16 FPS (适合大多数文戏)。
         - 动作戏/快速镜头：24 FPS。
       - **Length 计算公式**：(FPS * Duration) + 1。
       - 示例：
         - 5秒, 16FPS -> 81帧
         - 8秒, 24FPS -> 193帧
       
    {dialogues_constraint}

    {ltx_audio_instruction}

    【输出格式】
    必须是合法的 JSON格式：
    {{
      "prompt_pos": "...",
      "prompt_neg": "...",
      "fps": 16,
      "length": 49,
      "duration_reasoning": "动作简单，3秒足够展示..."
    }}
    """

    user_prompt = f"""
    【场景与角色上下文】
    {video_context_str}

    请生成用于图生视频的 prompt_pos 和 prompt_neg。
    请注意：
    1. 必须融入画风【{style_name}】的风格词。
    2. 绝对不要出现人名，用"年轻人/妇女"等通用词。
    3. 准确描述人物位置和动作。
    5. 必须返回建议的 FPS 和 Length (计算公式: fps * 秒数 + 1)，推荐 5秒，最长不超过 10 秒。
    """

    if config.LLM_LOG:
        print("-" * 50)
        print("【LLM Video Prompt Input】")
        print(system_prompt)
        print(user_prompt)
        print("-" * 50)

    try:
        is_doubao = "volces.com" in llm_profile.base_url or "doubao" in model_name.lower()
        
        params = {
            "model": llm_profile.model or "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.7,
            "timeout": 120 # Increased timeout for merge planning
        }
        
        if not is_doubao:
            params["response_format"] = {"type": "json_object"}

        completion = client.chat.completions.create(**params)
        
        content = completion.choices[0].message.content
        
        if config.LLM_LOG:
            print("【LLM Video Prompt Output】")
            print(content)
            print("-" * 50)
        
        result = json.loads(content)
        result["_usage"] = completion.usage.model_dump()
        return result

    except Exception as e:
        print(f"LLM Video Prompt Error: {e}")
        # Fallback
        return {
            "prompt_pos": "High quality video, cinematic lighting, detailed scene, dynamic motion.",
            "prompt_neg": "low quality, static, deformed, watermark, text"
        }

def generate_scene_prompts(base_desc: str, style_preset=None, llm_profile=None, scene_type="Indoor", player_count=0) -> dict:
    if not llm_profile:
        raise ValueError("No LLM Profile provided. Please configure LLM in Settings.")

    client = OpenAI(
        api_key=llm_profile.api_key,
        base_url=llm_profile.base_url
    )
    
    # Use profile model or fallback
    model_name = llm_profile.model or "gpt-3.5-turbo"
    
    style_name = style_preset.name if style_preset else "默认通用风格"
    style_guard = style_preset.llm_style_guard if style_preset else "无特殊风格约束，保持写实。"
    style_pos = style_preset.style_pos if style_preset else ""
    style_neg = style_preset.style_neg if style_preset else ""
    # Add engine hint for model-specific prompting
    engine_hint = f"{style_preset.engine_hint}" if style_preset and style_preset.engine_hint else "本项目使用 Qwen Image / Wan2.2 图像模型"
    
    # Scene Type Constraints
    type_constraint = ""
    st_lower = str(scene_type).lower()
    
    if st_lower == "indoor":
        type_constraint = "这是【室内场景】。必须符合室内空间逻辑，避免出现天空、远景地平线、室外自然景观。"
    elif st_lower == "outdoor":
        type_constraint = "这是【室外场景】。必须包含自然光照、天空或环境背景，避免出现封闭的室内天花板。"
    elif st_lower == "special":
        type_constraint = "这是【特殊/超现实场景】。可以突破常规物理逻辑，强调概念设计与独特氛围。"
    
 
    player_constraint = "这是纯场景底图，画面中禁止出现任何人物、角色。"
    
    system_prompt = f"""你是一个【图像场景生成提示词清洗与重写器】。
    
    【项目画风名称】
    {style_name}
    
    【项目画风正向（必须融入 prompt_pos）】
    {style_pos}
    
    【项目画风反向（必须融入 prompt_neg）】
    {style_neg}
    
    【画风守卫（自然语言约束，必须遵守）】
    {style_guard}
    
    【下游生成模型，你输出的提示词必须可直接用于这个 Comfyui 模型】
    {engine_hint}
    
    【场景类型约束】
    {type_constraint}
    {player_constraint}

    【特殊场景规则：系统/虚拟界面 (CRITICAL)】
    - **触发条件**：如果输入描述中包含“系统界面”、“虚拟面板”、“属性面板”、“系统提示”、“虚拟屏幕”、“金手指”、“系统空间”等概念，或者角色身份为“系统”。
    - **强制执行**：
      - **背景必须为**：**"Simple Black Background" (纯黑背景)** 或 **"Solid Color Background" (纯色背景)**。
      - **绝对禁止**：禁止生成复杂的科技元素（如：数据流、扫描线、网格、全息投影、复杂的UI组件、文字、发光特效）。
      - **原因**：系统界面将由后期合成，场景底图必须是干净的纯色，方便抠图与合成。
    
    你的任务是： 
    在保持原有画面风格、镜头语言、氛围与美术一致性的前提下，
    对输入的提示词进行整理、强化与重写，
    并最终输出【可直接用于图像生成模型的正向提示词与负向提示词】。

    【⚠️ 核心强制规则（必须严格遵守）】 
    1. 如果输入内容中出现：
       - 任何人物姓名（如：陈平安、宁姚等）
       - 任何人物身份、角色、主角、配角描述
       - 任何暗示“有人在场 / 人物出现 / 人物行为”的内容 
       👉 一律 **忽略、删除，不得保留，不得替换为“某人”“人物剪影”等变体**。

    2. 最终输出的提示词中：
       - **不能出现任何人物**
       - **不能暗示人物存在**
       - **不能出现人形、生物主体、角色轮廓**
       - 画面必须是【纯场景 / 纯环境 / 纯空间表达】

    3. 即使原始描述以人物为核心，
       你也必须只提取：
       - 场景结构
       - 建筑 / 自然环境
       - 光影、天气、时间
       - 氛围、情绪、美术风格
       - 摄影机语言（景别、角度、构图）
    
    4. **风格保持规则**：
       - 保持原有项目指定的画风与美术体系 
       - 不要引入新的题材或风格 
       - 不要写实转卡通 / 不要卡通转写实 
       - 不主动增加不存在的剧情元素 
       
    5. **画风词清洗**：
       - 仔细检查【项目画风正向】中的词汇。
       - 如果其中包含“五官、发型、肤色、眼睛、手指、肢体”等人物特有的描述，**必须将其剔除**，不要带入到场景提示词中。
       - 只保留画风中关于“光影、色彩、笔触、材质、渲染风格”的描述。

    你的目标是： 
    👉 让生成模型只看到一个“强氛围、强构图、无人存在的电影级场景画面”。

    你生成的描述将被系统整理为以下结构：
    - 核心约束 (System Injected)
    - 镜头景别 (Shot Type)
    - 场景结构
    - 材质与固定元素
    - 光影与环境
    - 画面与质感

    对于 prompt_pos 字段，请务必按以下【标签格式】分段输出内容：

    【镜头景别】
    (这里写：远景/全景/中景/特写，以及视角描述，如：广角俯视/平视/仰视等)

    【场景结构】
    (这里写空间类型与布局：室内/室外/建筑结构/道路/山体/房间构造等，多行短句)

    【材质与固定元素】
    (这里写墙面/地面/顶棚/梁柱/门窗/家具/固定物件，多行短句)

    【光影与环境】
    (这里写自然光/人造光/阴影关系/空气透视/雾尘雨雪等，多行短句)

    【画面与质感】
    (这里写超清晰/细节丰富/真实材质纹理/干净画面等)
    """
    
    user_prompt = f"""
    请将下面的“场景基础描述”扩写为可直接用于 Qwen Image 文生图的结构化提示词，并生成反向提示词与场景指纹。

    【场景基础描述】
    {base_desc}

    【输出 JSON 字段】
    - prompt_pos: 严格按照 System Prompt 中的【标签格式】输出，包含：镜头景别、场景结构、材质与固定元素、光影与环境、画面与质感。
    - prompt_neg: 反向提示词（逗号或换行）
    - scene_desc: 只包含场景客观结构/材质/光照等，不写人物、不写镜头、不写情绪、不写用途
    - shot_type: 单独输出景别类型 (如: "远景", "全景", "中景", "特写")
    """

    # --- Debug Logging Start ---
    if config.LLM_LOG:
        print("\\n" + "="*50)
        print(f" [LLM SCENE Request] Provider: {llm_profile.provider} | Model: {model_name}")
        print("-" * 20 + " System Prompt " + "-" * 20)
        print(system_prompt.strip())
        print("-" * 20 + " User Prompt " + "-" * 20)
        print(user_prompt.strip())
        print("="*50 + "\\n")
    # --- Debug Logging End ---

    try:
        is_doubao = "volces.com" in llm_profile.base_url or "doubao" in model_name.lower()
        
        params = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "timeout": 120 # Increased timeout for long story generation
        }
        
        if not is_doubao:
            params["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**params)
        
        content = response.choices[0].message.content
        
        # --- Debug Logging Start ---
        if config.LLM_LOG:
            print("\\n" + "="*50)
            print(" [LLM SCENE Response]")
            print("-" * 20 + " Raw Content " + "-" * 20)
            print(content)
            print("="*50 + "\\n")
        # --- Debug Logging End ---
        
        usage = response.usage.model_dump() if response.usage else {}
        
        result = {}
        # Robust JSON extraction
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
            if match:
                result = json.loads(match.group(1))
            else:
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    result = json.loads(match.group(0))
                else:
                    # Retry logic
                    print(" [Warning] JSON Parse Failed. Attempting repair retry...")
                    repair_prompt = "上一次输出不是合法的 JSON 格式。请修正格式，只输出纯 JSON，不要包含 Markdown 代码块或其他文字。"
                    repair_resp = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                            {"role": "assistant", "content": content},
                            {"role": "user", "content": repair_prompt}
                        ],
                        response_format={"type": "json_object"}
                    )
                    repair_content = repair_resp.choices[0].message.content
                    print(f" [LLM Repair Response] {repair_content}")
                    try:
                        match = re.search(r'\{.*\}', repair_content, re.DOTALL)
                        if match:
                            result = json.loads(match.group(0))
                        else:
                            raise ValueError(f"无法解析 LLM 返回的 JSON (重试后): {repair_content}")
                    except:
                         raise ValueError(f"无法解析 LLM 返回的 JSON: {content}")

        # Merge usage info
        result["_usage"] = usage
        
        # --- Normalize Prompt Structure ---
        if "prompt_pos" in result:
            raw_pos = result["prompt_pos"]
            normalized_pos = normalize_scene_prompt_structure(raw_pos, style_name, style_pos)
            result["prompt_pos"] = normalized_pos
            print(f" [Normalized Scene Prompt] \\n{normalized_pos}")

        # --- Normalize Negative Prompt ---
        # 叠加 style_neg 和 系统补强
        raw_neg = result.get("prompt_neg", "")
        normalized_neg = normalize_scene_negative_prompt(raw_neg, style_neg)
        result["prompt_neg"] = normalized_neg
        print(f" [Normalized Scene Neg Prompt] {normalized_neg}")

        return result
            
    except Exception as e:
        raise Exception(f"OpenAI API Error ({llm_profile.provider}): {str(e)}")

def generate_merge_prompts(
    scene_base_desc: str,
    players: list,
    style_preset=None,
    llm_profile=None,
    scene_desc: str = "",
    scene_type: str = "Indoor",
    image_model: str = "qwen"
) -> dict:
    """
    Generate ordered merge steps and prompts for Scene Merge.
    players: list of dict { "player_id", "player_name", "appearance", "views_keys" }
    image_model: "qwen" or "z_image_turbo" to switch view_key logic.
    """
    if not llm_profile:
        raise ValueError("No LLM Profile provided.")

    client = OpenAI(
        api_key=llm_profile.api_key,
        base_url=llm_profile.base_url
    )
    
    style_name = style_preset.name if style_preset else "默认通用风格"
    style_guard = style_preset.llm_style_guard if style_preset else "无特殊风格约束。"
    style_pos = style_preset.style_pos if style_preset else ""
    style_neg = style_preset.style_neg if style_preset else ""
    # Add engine hint for model-specific prompting
    engine_hint = f"{style_preset.engine_hint}" if style_preset and style_preset.engine_hint else "本项目使用 Qwen Image / Wan2.2 图像模型"
    
    # Ensure model_name is defined before use
    model_name = llm_profile.model or "gpt-3.5-turbo"

    # Z-Image Turbo Instruction Logic
    # 统一规则：不再区分模型，所有模型遵循统一的视角逻辑
    z_image_instruction = """
   - **view_key 核心规则 (Unified View Logic)**：
     - **Front**: 代表 **正面** (Facing Camera)。如果需要人物正对镜头（无论是特写还是全身），请优先返回 `front`。注意：`views_keys` 列表中可能没有 `front`，但你**必须**直接返回 `front` 字符串，系统会自动映射到基础图。
     - **Wide**: 代表 **背影/背面** (Back View / Walking Away)。如果需要人物背对镜头，请返回 `wide`。
     - **Close**: 代表 **特写/半身** (Close-up)。如果需要人物面部特写，优先返回 `close`。
     - **Side/Right45/Left45**: 代表 **侧面/侧身**。
     
     - **特别注意**：
       - 严禁将 `wide` 用于正面镜头。
       - 严禁将 `front` 用于背面镜头。
       - 即使 `views_keys` 中没有 `front`，你也应该在需要正面图时返回 `front`。
    """
    
    # Construct Players Info for Prompt
    players_data_for_prompt = []
    for p in players:
        # Determine Sex from player object
        # The 'appearance' field in players list passed here comes from manager.py
        # manager.py passes: "appearance": p.player_mark or p.player_desc or ""
        # It does NOT pass p.player_sex directly in the dict.
        # But manager.py constructs the dict. We should update manager.py to pass sex.
        # However, we are in openai_provider.py.
        # Let's check what keys are in p.
        
        # If 'sex' key exists (we will update manager.py to send it), use it.
        # Otherwise fallback to parsing appearance.
        sex_val = p.get("sex", "人物")
        # Normalize database sex values to simpler terms for prompt
        if str(sex_val).lower() in ["male", "男", "男性"]:
            sex_val = "男性"
        elif str(sex_val).lower() in ["female", "女", "女性"]:
             sex_val = "女性"
        else:
             # Fallback
             app_str = str(p.get("appearance", ""))
             if "男" in app_str:
                 sex_val = "男性"
             elif "女" in app_str:
                 sex_val = "女性"
             else:
                 sex_val = "人物"
        
        players_data_for_prompt.append({
            "player_id": p.get("player_id"),
            "player_name": p.get("player_name"),
            "sex": sex_val,
            "views_keys": p.get("views_keys")
        })
    players_info = json.dumps(players_data_for_prompt, ensure_ascii=False, indent=2)
    
    # Branch Logic: Single Player vs Multi Player
    is_single_player = len(players) == 1
    
    if is_single_player:
        # --- Single Player Optimized Prompt ---
        system_prompt = f"""你是一个专业的图像合成编排器（单人精细化模式）。
Your task is to plan the perfect composition for a single character based on the [Scene Detailed Fingerprint] and [Scene Basic Description].

【项目画风】
{style_name}
{style_guard}

【画风正向（参考）】
{style_pos}

【画风反向（参考）】
{style_neg}

【下游生成模型，你输出的提示词必须可直接用于这个 Comfyui 模型】
{engine_hint}

【场景类型】
{scene_type}

【任务目标】
当前场景只有一名角色。你需要充分利用场景描述中的氛围、光影、细节，让角色完美融入其中。
**关键挑战**：原始人物素材图片可能很大（如半身像），你必须通过提示词强制缩小人物比例，使其适配场景空间，避免人物过大充满屏幕。

【强制规则】
1. **merge_pos (核心)**：
   - 必须是一段流畅的自然语言描述。
   - **格式要求**：包含“将 image2 图中唯一的[性别]人物增加到 image1 的[位置]”这一核心指令。
   - **人物替换增强 (Crucial)**：
     - 如果 image1 (场景图) 中看起来已经存在模糊的人物轮廓或占位符，**必须**在提示词中明确要求“用 image2 的人物替换 image1 中的原有轮廓/人物”。
     - 提示词追加：“replace existing figure in image1 with image2 character”。
   - **视点与比例自适应 (Crucial)**：
     - **检测场景描述中的视点**：仔细阅读【场景基础描述】。
     - **如果是特写 (Close-up)**：
       - **必须使用** "close up", "portrait", "upper body" 等特写比例词。
       - **禁止使用** "full body", "small scale", "wide shot"。
       - **位置**：通常是 "中间" 或 "中间前景"。
       - **示例**："将 image2 图中唯一的男性人物合并到 image1 的中间前景。特写(close up)，半身像(upper body)，面部表情清晰，背景虚化。"
     - **如果是全景/远景 (Wide/Long Shot)**：
       - **必须使用** "full body", "wide shot", "small scale"。
       - **示例**："将 image2 图中唯一的男性人物合并到 image1 的中间中景。全身像(full body)，人物比例较小(small scale)。"
   - **推荐格式**："将 image2 图中唯一的[性别]人物合并到 image1 的[位置]。[比例描述]，人物[动作描述]，[神态描述]，[与环境的交互]。[光影融合描述]。"
   - **禁止**：禁止写“image1”或“image2”以外的图片代号。
   

2. **merge_neg (核心)**：
   - 保持原有的严格约束（禁止换脸、禁止重绘背景等）。
   - **禁止出现任何人物姓名**。
   - **禁止与视点冲突**：如果是特写场景，禁止写 "全身"；如果是全景场景，禁止写 "特写"。

3. **view_key 选择 (Strict Logic)**：
   - **特写场景优先**：如果【场景基础描述】中包含“特写”、“Close-up”、“面部”、“眼神”等关键词，且 `views_keys` 中有 `close`，**必须优先选择 `close`**。如果没有 `close`，选择 `front` 或 `low`。
   - **普通场景优先**：根据动作和站位选择 `right45`, `left45`, `front` 等。
   - **背影/背面场景优先**：如果场景需要人物背对镜头，优先选 `wide`。
   - **尽量不选择**：`low`, `aerial`，因为在实际测试中效果不理想。
   {z_image_instruction}
   - **示例**：
     - 如果人物站在左侧面向右侧，优先选 "right45" 或 "side"。


输出结构 (JSON)：
{{
  "layout_reasoning": "分析场景氛围与角色关系，构思动作与比例...",
  "steps": [
    {{
      "player_id": 123,
      "player_name": "角色名",
      "view_key": "right45",
      "merge_pos": "将 image2 的[性别]人物合并到 image1 的...",
      "merge_neg": "..."
    }}
  ]
}}
"""
    else:
        # --- Multi Player Standard Prompt (Original) ---
        system_prompt = f"""你是一个专业的图像合成编排器。
你的任务是根据【场景详细指纹】和【可用角色列表】，规划角色合成的步骤，并生成每一步的提示词。

【项目画风】
{style_name}
{style_guard}

【画风正向（参考）】
{style_pos}

【画风反向（参考）】
{style_neg}

【下游生成模型，你输出的提示词必须可直接用于这个 Comfyui 模型】
{engine_hint}

【场景类型】
{scene_type}

【强制规则】
1. **全局空间规划 (Crucial)**：
   - 必须先分析场景的透视结构（前景、中景、远景）。
   - **防重叠 (Collision Avoidance)**：必须明确分配每个角色的站位。例如：A在左侧中景，B在右侧远景。
   - **比例控制 (Scale Control)**：原始人物素材图片很大，合成时必须要求人物以【全身、中远景】融入场景。避免“巨型人物”填满画面。
   - **错位分布 (Staggered Layout)**：不要将所有人物安排在同一水平线上。利用纵深感，将人物安排在不同深度（前景/中景/远景），形成错落有致的构图。
   - 严禁让两个角色出现在同一个坐标点，或者发生身体穿插。

2. **体型差与年龄感 (Age) - NEW & CRITICAL**:
   - **必须分析角色名字中的后缀属性**（如：幼年、少年、青年、成年等）。
   - **如果角色是“幼年/儿童”**：
     - **站位调整**：儿童通常位于画面中下部或前景低处。

3. **merge_pos 必须极其简短与明确 (Simple & Precise)**：
   - **下游模型理解能力有限，禁止复杂的方位描述**。
   - **格式必须为**：“将 image2 图中唯一的[性别]人物增加到 image1 的[位置]，[比例描述]，[简短动作]”。
   - **位置词只能是以下之一**（尽量少用前景，多用中景）：
     - 左侧中景 / 右侧中景 / 中间中景 (推荐)
     - 远景左侧 / 远景右侧 / 远景中间 (推荐)
     - 左侧前景 / 右侧前景 / 中间前景 (仅当需要特写时使用)
   - **比例描述词 (必须包含)**：full body (全身), wide shot (广角), in the distance (远处)。
   - **禁止**：禁止写“靠近XXX物体”、“在XXX之后”、“形成XXX构图”等复杂修饰语。
   - **允许**：可以包含简短的动作描述，如“站立”、“坐着”、“行走”、“挑水”、“扫地”等，但必须极其简练。
   - **禁止**：禁止在 merge_pos 中描述朝向、光影、复杂的交互细节。这些统统不要写！只写位置和核心动作！
   - **示例**：
     - 正确："将 image2 图中唯一的男性人物增加到 image1 的左侧中景，全身像(full body)，正在挑水"
     - 正确："将 image2 图中唯一的女性人物增加到 image1 的右侧远景，全身(full body)，站立"
     - 错误："将 image2 合成在柜台后方靠近窗户的位置..." (太复杂)

4. **merge_neg 必须包含**：
   - 禁止重绘背景/改变光照风格。
   - 禁止新增文字/水印/logo。
   - 禁止裁切人物（头顶/脚/鞋都不能缺）。
   - **核心禁止**：禁止改变、替换或覆盖 image1 中已经存在的任何人物（keep existing characters unchanged）。
   - 禁止把人物变成其他人/换脸/换衣。
   - **禁止出现任何人物姓名（如“陈平安”），必须使用通用描述**。
   - **禁止人物重叠/穿模/多头多手**。
   - **禁止人物过大/大头照/半身像** (close up, portrait)。

5. **view_key 选择 (Strict Match)**：
   - 必须从角色的 `views_keys` 列表中选择最匹配的一个。
   - **禁止滥用 "wide" 或 "front"**：仅在明确需要背影或正脸特写时使用。如果角色有 "side", "right45", "back" 等更具体的视角，优先使用这些视角来匹配人物在场景中的朝向和站位。
   {z_image_instruction}
   - **示例**：
     - 如果人物站在左侧面向右侧，优先选 "right45" 或 "side"。

输出结构 (JSON)：
{{
  "layout_reasoning": "简短的中文思考：分析场景结构，为了避免拥挤，将角色A安排在远景...",
  "steps": [
    {{
      "player_id": 123,
      "player_name": "角色名",
      "view_key": "right45",
      "merge_pos": "将 image2 的[性别]人物增加到 image1 的[位置],[动作]",
      "merge_neg": "多行中文负面..."
    }}
  ]
}}
"""

    user_prompt = f"""
【场景基础描述】
{scene_base_desc}

【场景详细指纹 (Scene Fingerprint)】
{scene_desc}

【可用角色映射表】
{players_info}

请生成合成步骤，确保人物不重叠，符合场景透视。
"""

    print("-" * 50)
    print("【LLM Merge Input】")
    print(system_prompt)
    print(user_prompt)
    print("-" * 50)

    try:
        is_doubao = "volces.com" in llm_profile.base_url or "doubao" in model_name.lower()
        
        params = {
            "model": llm_profile.model or "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.7,
            "timeout": 120 # Increased timeout for video prompts
        }
        
        if not is_doubao:
            params["response_format"] = {"type": "json_object"}

        completion = client.chat.completions.create(**params)
        
        content = completion.choices[0].message.content
        print("【LLM Merge Output】")
        print(content)
        print("-" * 50)
        
        result = json.loads(content)
        
        # Validation
        if "steps" not in result or not isinstance(result["steps"], list):
            # Fallback: create 1 step for first player
            p0 = players[0]
            result = {
                "steps": [{
                    "player_name": p0["player_name"],
                    "view_key": "right45" if "right45" in p0["views_keys"] else "front",
                    "merge_pos": f"{p0['player_name']} standing in scene, natural lighting, contact shadow",
                    "merge_neg": "floating, bad shadow, extra people"
                }]
            }
            
        result["_usage"] = completion.usage.model_dump()
        return result

    except Exception as e:
        print(f"LLM Merge Prompt Error: {e}")
        # Fallback
        if players:
            p0 = players[0]
            return {
                "steps": [{
                    "player_name": p0["player_name"],
                    "view_key": "right45",
                    "merge_pos": "character standing in scene, natural lighting, contact shadow",
                    "merge_neg": "floating, bad shadow"
                }]
            }
        return {"steps": []}

def generate_story_assets(
    story_content: str,
    style_preset=None,
    llm_profile=None,
    episode_start=1,
    max_characters=5,
    max_scenes=10,
    single_only=False
) -> dict:

    if not llm_profile:
        raise ValueError("No LLM Profile provided. Please configure LLM in Settings.")

    client = OpenAI(
        api_key=llm_profile.api_key,
        base_url=llm_profile.base_url
    )

    model_name = llm_profile.model or "gpt-4.1-mini"

    # =========================
    # System Prompt
    # =========================
    system_prompt = f"""
【ROLE】
你是一个影视项目结构拆分器，为自动漫剧 / 视频生成系统服务。

【ABSOLUTE RULES（最高优先级）】
1. 只允许输出【一个合法 JSON 对象】
2. 禁止输出 JSON 以外的任何文字
3. 禁止生成：prompt_pos / prompt_neg / player_desc / scene_desc / 标签结构
4. scenes[].episode 必须【严格等于 {episode_start}】
5. 所有角色引用必须【完整一致，禁止简称、别名、省略】

【STYLE LOCK】


【CHARACTER TASK】
从剧情中提取主要人物（最多 {max_characters} 个），每个角色必须包含：
- player_name（严格命名规范）
- player_sex（male / female / other）
- height_cm（整数，单位 cm，必须合理）
- player_mark（详细外貌 + **身材比例 (CRITICAL)** + 穿着）

【HEIGHT & PROPORTION RULE（CRITICAL）】
- height_cm 必须是【纯整数】（单位 cm），若原文未提及，需合理推断。
- player_mark 必须包含：
  1. **明确的身高描述**（e.g., "身高约175cm", "身形高大", "娇小玲珑"）。
  2. **身材比例描述**（e.g., "修长双腿", "八头身比例", "宽肩窄腰", "上身较短下身修长"）。
  3. **禁止**出现五五身、上下身等长等不协调描述。
  4. 必须能被文生图模型理解，用于生成正确的全身立绘。

【SCENE / SHOT TASK】
将剧情拆解为【可直接生成的镜头 Shot】（最多 {max_scenes} 个）：
- scenes 数组中的【每一项 = 一个独立 Shot】
- 每个 Shot 必须可直接用于图像 / 视频生成

【SHOT OUTPUT REQUIRED FIELDS】
- name
- episode（固定为 {episode_start}）
- shot（从 1 递增）
- scene_type（Indoor / Outdoor / Special）
- base_desc（完整、自包含的环境 + 氛围描述）
- characters（本 Shot 出镜角色）
- dialogues（对白数组，用于口型生成）

【DIALOGUE RULE（CRITICAL）】
- dialogues 是【核心字段】，不得随意省略
- 只要剧情中存在语言交流，就必须生成对白
- 每条对白结构：
  {{ "role": "完整角色名", "content": "该角色实际说的话" }}
- 无对白的 Shot，必须返回空数组 []

【CHARACTER CONSISTENCY（CRITICAL）】
- scenes[].characters 中的名字
- dialogues[].role 中的名字
必须【严格等于】characters[].player_name

禁止任何未声明角色出现。

"""

    # =========================
    # Shot Constraint
    # =========================
    if single_only:
        system_prompt += """
【SHOT MODE：SINGLE ONLY】
- 每个 Shot 的 characters 数组【必须且只能包含 1 人】
- 多人对话必须拆为 Shot-Reverse-Shot
- 每个 Shot 只允许该角色说话
"""
    else:
        system_prompt += """
【SHOT MODE：NORMAL】
- 每个 Shot 最多 2 人
- 超过 2 人必须拆分
- 战斗/围观等场景可多人同框，但需在 base_desc 中明确说明
"""

    system_prompt += """
【CAMERA HINT】
- 单人 Shot 请明确暗示构图：
  - Close-up（面部特写，背景虚化）
  - Front（正视全景）
  - Wide（背影/背面图）


【BASE_DESC RULE】
- 必须是完整、自包含描述
- 严禁“同上 / 延续 / 和之前一样”等指代性语言

【SYSTEM / VIRTUAL UI RULE (CRITICAL)】
- 如果剧情涉及“系统界面”、“查看属性”、“系统提示”、“虚拟面板”等虚拟UI交互，或者场景是“系统空间”：
- base_desc 必须描述为：“纯黑背景，无其他细节。”（Pure Black Background）
- 禁止描述具体的UI细节（如文字内容、边框样式、数据流、扫描线），因为这些无法被生图模型准确生成，且会干扰后期合成。
- 确保场景为纯净的底色，方便后期贴图。

【ABSOLUTE SPACE RULE（CRITICAL）】
- base_desc 必须使用【绝对空间描述】，不得依赖其他 Shot 的场景存在
- 禁止使用任何“相对位置 / 相对参照”表达，包括但不限于：
  - “旁 / 边 / 附近 / 不远处 / 远处可见”
  - “路旁 / 林边 / 官道旁 / 房屋外侧”
  - “在某某附近 / 靠近某物”
- 每个 base_desc 必须【独立定义一个完整可生成的空间】
- 正确方式示例：
  ❌ 官道旁的密林边缘
  ✅ 深秋山林中，一条被落叶覆盖的狭窄土路贯穿其间，高大树木在两侧形成压迫性的林墙
"""


    # =========================
    # User Prompt
    # =========================
    user_prompt = f"""
    剧情梗概：
    {story_content}
    
    请输出 JSON，结构如下：
    
    {{
      "characters": [
        {{
          "player_name": "",
          "player_sex": "male/female/other",
          "player_mark": ""
        }}
      ],
      "scenes": [
        {{
          "name": "",
          "episode": {episode_start},
          "shot": 1,
          "scene_type": "Indoor/Outdoor/Special",
          "base_desc": "",
          "characters": ["角色A", "角色B"],
          "dialogues": [
            {{
                "role": "角色A",
                "content": "这里写该角色说的话..."
            }}
          ]
        }}
      ]
    }}
    
    说明：
    1）player_mark 必须是：详细的外貌 + 属性备注，不包含提示词标签，不包含 prompt，不包含合成说明，不包含结构标签
    2）关于角色命名规范（严格执行）：
       格式必须为：姓名（年龄阶段） 或 姓名（年龄阶段）（特定状态）
       - 姓名：角色本名，不带修饰。
       - 年龄阶段（必选）：只能从以下词汇中选择一个：[幼年, 少年, 青年, 中年, 老年]。
       - 特定状态（可选）：仅当角色身份或服装有重大特殊性时添加，如：(戎装)、(红衣)、(乞丐装)、(掌柜)。
       
       错误示例：
       - 陶掌柜（中年·杂货铺主） -> 错误，使用了"·"且描述过长
       - 李逍遥（少年剑客） -> 错误，"少年剑客"未拆分
       
       正确示例：
       - 陈平安（少年）
       - 陶掌柜（中年）（杂货铺主）
       - 李逍遥（青年）
       - 林月如（青年）（戎装）
       
       相应的 `player_mark` 必须准确描述该时期的特定年龄、外貌和着装。
    3）base_desc 必须是：场景基础描述，世界观 + 氛围 + 关键元素，不包含提示词结构，不包含负面提示词
       - **CRITICAL**: 每个 base_desc 必须包含**明确的画面与镜头描述**。
       - **CRITICAL**: 如果单人模式下存在连续镜头，必须为每个镜头**重新书写完整、独立的环境描述**。
       - **CRITICAL**: 严禁使用“同一间”、“同上”、“环境同前”等指代性词汇。每个描述都必须是**自包含 (Self-contained)** 的。
       - **CRITICAL**: 必须包含镜头语言（如：特写/全景），以及光影氛围描述。
       - 错误示例：“同一间书院静室，光线更落在少年脸上”（缺少环境细节，使用了指代）
       - 错误示例：“山林土路尽头形成一处狭窄洼地...”（缺少镜头视角描述）
       - 正确示例：“古风书院静室内，柔和光线透过木窗，书案上墨香四溢。镜头为近景特写(Close-up)，聚焦在少年沉静的侧脸，背景书架虚化。”
    4）scenes[].characters 必须是 characters[].player_name 的子集，如场景无人则为空数组 []
    5）scene_type 必须是 "Indoor", "Outdoor" 或 "Special"
    6）dialogues 用于口型生成，请根据剧情合理分配对白。
    """

    # =========================
    # Debug
    # =========================
    if config.LLM_LOG:
        print("=" * 60)
        print("[LLM STORY REQUEST]")
        print(system_prompt)
        print(user_prompt)
        print("=" * 60)

    try:
        is_doubao = (
            "volces.com" in llm_profile.base_url
            or "doubao" in model_name.lower()
        )

        params = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "timeout": 120
        }

        if not is_doubao:
            params["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**params)
        content = response.choices[0].message.content.strip()

        if config.LLM_LOG:
            print("[LLM RAW RESPONSE]")
            print(content)

        # =========================
        # JSON Parse & Repair
        # =========================
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r'\{[\s\S]*\}', content)
            if not match:
                raise ValueError("No JSON object found")

            json_str = match.group(0)
            json_str = json_str.replace('“', '"').replace('”', '"')
            json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
            result = json.loads(json_str)

        # =========================
        # Post Validation
        # =========================
        for c in result.get("characters", []):
            if "height_cm" not in c or not isinstance(c["height_cm"], int):
                raise ValueError(f"Invalid height_cm for character {c.get('player_name')}")

        if single_only:
            for s in result.get("scenes", []):
                # Ignore empty characters for Special scenes (like black screen, system UI)
                if s.get("scene_type") == "Special" and len(s.get("characters", [])) == 0:
                    continue
                    
                if len(s.get("characters", [])) != 1:
                    # Allow empty characters in general? Maybe just for Special/Empty scenes.
                    # But if single_only is enforced, usually we want exactly one character.
                    # However, "Death screen" or "Scenery only" might have 0 characters.
                    # Let's relax the rule: Must be <= 1 character.
                    if len(s.get("characters", [])) == 0:
                        continue
                    raise ValueError(f"Single-only violation at shot {s.get('shot')}: found {len(s.get('characters', []))} characters")
                
                # Check dialogues only if characters exist
                if s.get("characters"):
                    for d in s.get("dialogues", []):
                        if d["role"] != s["characters"][0]:
                            # In single mode, if there is dialogue, it must belong to the single character present
                            # Unless it's a voiceover? But prompt says "role" must be in "characters".
                            # Let's keep it strict but maybe allow partial match?
                            # For now, strict match is fine if LLM follows instructions.
                            # But if LLM hallucinates a name not in scene characters, we might want to warn instead of fail?
                            # Let's stick to fail to ensure quality, but maybe relax for voiceover if we supported it.
                            raise ValueError(f"Dialogue role mismatch in single_only mode at shot {s.get('shot')}")

        result["_usage"] = response.usage.model_dump() if response.usage else {}
        return result

    except Exception as e:
        raise Exception(f"OpenAI API Error ({llm_profile.provider}): {str(e)}")