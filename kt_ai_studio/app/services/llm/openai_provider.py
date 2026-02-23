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
        "纯背景",
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
        
    return "\n".join(final_parts).strip()

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

def generate_player_prompts(name: str, sex: str, mark: str, style_preset=None, llm_profile=None) -> dict:
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

你的任务：
1) 仅在该画风下扩写人物细节
2) 不得改变画风，必须融入 Positive 风格词
3) 输出必须详细，适合图像模型理解
4) 不要出现人物名字
5) 不要出现“适合合成 / 稳定 / 图生视频”等系统说明
6) 所有输出内容【只能使用中文】
7) 输出格式【必须是合法 JSON】

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
    - 纯人物，无背景
    - 基础服装（用于后续换装）
    
    请输出 JSON：
    {{
      "prompt_pos": "严格按照 System Prompt 中的【标签格式】输出，包含：人物外观、体型与姿态、服装、画面与质感。必须包含：全身图、纯背景",
      "prompt_neg": "避免画风漂移、比例错误、低质量、半身、裁切",
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
        # Standard OpenAI-compatible call
        # Note: Some providers might need slight adjustments, but chat.completions is standard.
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"}
        )
        
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

def generate_scene_prompts(base_desc: str, style_preset=None, llm_profile=None, scene_type="Indoor") -> dict:
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
    
    system_prompt = f"""你是“受控扩写器”，不是创作者。你必须严格服从【项目画风】约束，不允许改变画风。

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

【强制规则】
    1) 只能扩写“场景细节”，禁止输出人物、角色、人体、面孔、服装等内容。
    2) 必须输出镜头景别（shot_type）：明确是远景、全景、中景还是特写，并写入 prompt_pos。
    3) 禁止输出情绪与剧情：禁止“紧张/温馨/诡异/悬疑”等情绪词。
    4) 你必须输出中文，并且只输出 JSON（不要输出任何解释、注释、前后缀文字）。
    5) prompt_pos 必须是“结构化分段文本”，按固定顺序输出，且每段多行短句。
    6) scene_desc 必须是“客观场景指纹”：只写空间结构/材质/固定物件/光照，不写人物、不写镜头、不写用途。

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
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"}
        )
        
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
    scene_type: str = "Indoor"
) -> dict:
    """
    Generate ordered merge steps and prompts for Scene Merge.
    players: list of dict { "player_id", "player_name", "appearance", "views_keys" }
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
你的任务是根据【场景详细指纹】和【场景基础描述】，为唯一的角色规划最完美的合成方案。

【项目画风】
{style_name}
{style_guard}

【画风正向（参考）】
{style_pos}

【画风反向（参考）】
{style_neg}

【下游生成模型】
{engine_hint}

【场景类型】
{scene_type}

【任务目标】
当前场景只有一名角色。你需要充分利用场景描述中的氛围、光影、细节，让角色完美融入其中，并执行符合情境的动作。
不要局限于简单的“增加到某位置”，而要生成一段“富含动作与环境交互”的描述。

【强制规则】
1. **merge_pos (核心)**：
   - 必须是一段流畅的自然语言描述。
   - **格式要求**：虽然仍需包含“将 image2 的[性别]人物增加到 image1 的[位置]”这一核心指令（为了让下游识别位置），但随后必须紧跟详细的动作与环境描写。
   - **推荐格式**："将 image2 的[性别]人物增加到 image1 的[位置]。人物[动作描述]，[神态描述]，[与环境的交互]。[光影融合描述]。"
   - **示例**："将 image2 的男性人物增加到 image1 的中间前景。他正弯腰整理货架上的竹筐，神情专注，夕阳余晖洒在他的侧脸，影子拉长投射在青石路面上。"
   - **禁止**：禁止写“image1”或“image2”以外的图片代号。

2. **merge_neg (核心)**：
   - 保持原有的严格约束（禁止换脸、禁止重绘背景等）。
   - **禁止出现任何人物姓名**。

3. **view_key 选择**：
   - 根据你构思的动作和站位，从 `views_keys` 中选择最匹配的一个（如侧身动作选 side/45，正面对话选 front）。

输出结构 (JSON)：
{{
  "layout_reasoning": "分析场景氛围与角色关系，构思动作...",
  "steps": [
    {{
      "player_id": 123,
      "player_name": "角色名",
      "view_key": "right45",
      "merge_pos": "将 image2 的[性别]人物增加到 image1 的...",
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
   - **防重叠 (Collision Avoidance)**：必须明确分配每个角色的站位。例如：A在左侧前景，B在右侧中景。
   - 严禁让两个角色出现在同一个坐标点，或者发生身体穿插。

2. **merge_pos 必须极其简短与明确 (Simple & Precise)**：
   - **下游模型理解能力有限，禁止复杂的方位描述**。
   - **格式必须为**：“将 image2 的[性别]人物增加到 image1 的[位置]，[简短动作]”。
   - **位置词只能是以下之一**：
     - 左侧前景 / 右侧前景 / 中间前景
     - 左侧中景 / 右侧中景 / 中间中景
     - 远景左侧 / 远景右侧 / 远景中间
   - **禁止**：禁止写“靠近XXX物体”、“在XXX之后”、“形成XXX构图”等复杂修饰语。
   - **允许**：可以包含简短的动作描述，如“站立”、“坐着”、“行走”、“挑水”、“扫地”等，但必须极其简练。
   - **禁止**：禁止在 merge_pos 中描述朝向、光影、复杂的交互细节。这些统统不要写！只写位置和核心动作！
   - **示例**：
     - 正确："将 image2 的男性人物增加到 image1 的左侧前景，正在挑水"
     - 正确："将 image2 的女性人物增加到 image1 的右侧中景，站立"
     - 错误："将 image2 合成在柜台后方靠近窗户的位置..." (太复杂)

3. **merge_neg 必须包含**：
   - 禁止重绘背景/改变光照风格。
   - 禁止新增文字/水印/logo。
   - 禁止裁切人物（头顶/脚/鞋都不能缺）。
   - 禁止把人物变成其他人/换脸/换衣。
   - **禁止出现任何人物姓名（如“陈平安”），必须使用通用描述**。
   - **禁止人物重叠/穿模/多头多手**。

4. **view_key 选择**：
   - 必须从角色的 `views_keys` 列表中选择。

输出结构 (JSON)：
{{
  "layout_reasoning": "简短的中文思考：分析场景结构，分配角色A在X位置，角色B在Y位置...",
  "steps": [
    {{
      "player_id": 123,
      "player_name": "角色名",
      "view_key": "right45",
      "merge_pos": "将 image2 的[性别]人物增加到 image1 的[位置]",
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
        completion = client.chat.completions.create(
            model=llm_profile.model or "gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        
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

def generate_story_assets(story_content: str, style_preset=None, llm_profile=None, episode_start=1, max_characters=5, max_scenes=10) -> dict:
    if not llm_profile:
        raise ValueError("No LLM Profile provided. Please configure LLM in Settings.")

    client = OpenAI(
        api_key=llm_profile.api_key,
        base_url=llm_profile.base_url
    )
    
    model_name = llm_profile.model or "gpt-3.5-turbo"
    
    style_name = style_preset.name if style_preset else "默认通用风格"
    style_guard = style_preset.llm_style_guard if style_preset else "无特殊风格约束，保持写实。"
    style_pos = style_preset.style_pos if style_preset else ""
    style_neg = style_preset.style_neg if style_preset else ""
    # Add engine hint for model-specific prompting
    engine_hint = f"{style_preset.engine_hint}" if style_preset and style_preset.engine_hint else "本项目使用 Qwen Image / Wan2.2 图像模型"
    
    system_prompt = f"""你是一个影视项目结构拆分器。
    
当前项目已锁定画风，这是最高优先级。

画风名称：
{style_name}

画风守卫：
{style_guard}

【下游生成模型，你输出的提示词必须可直接用于这个 Comfyui 模型】
{engine_hint}

你的任务：

根据用户提供的剧情梗概：

1）提取主要人物（最多 {max_characters} 个）
2）为每个人物生成：
    - 姓名
    - 性别
    - 详细的“外貌/属性备注”（用于后续生成提示词）

3）拆分剧情为场景（最多 {max_scenes} 个）
4）为每个场景生成：
    - 场景名称
    - episode（必须从 {episode_start} 开始递增，本任务只生成第 {episode_start} 幕的内容）
    - shot（从 1 开始递增）
    - scene_type（场景类型：Indoor / Outdoor / Special）
    - 基础场景描述（用于后续提示词生成）
    - 出场角色列表（必须是提取出的人物姓名）

必须：

- 不要生成 prompt_pos
- 不要生成 prompt_neg
- 不要生成 player_desc
- 不要生成 scene_desc
- 不要生成标签结构
- 不要生成 JSON 以外内容
- 不要输出解释
- 所有输出必须为合法 JSON
- 你必须为每个场景给出 characters 字段（数组），列出该场景出镜的主要角色姓名。该数组中的姓名必须来自你输出的 characters 列表。
- scenes[].episode 必须等于 {episode_start}（单幕生成）
- scene_type 判定规则：
    - Indoor：明确室内/封闭空间（房间、车厢、走廊、实验室、控制室、地铁、商场、仓库等）
    - Outdoor：明确室外/开放空间（街道、广场、荒野、山林、天台、停车场、码头等）
    - Special：特殊空间/超自然/非典型（梦境、主神空间、传送通道、异次元、全息投影空间、纯UI空间、抽象背景、强概念装置空间等）
    - 若混合但主要发生在室内则Indoor，主要在室外则Outdoor，无法归类或明显超现实则Special。必须严格区分大小写。
"""
    
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
      "characters": ["角色A", "角色B"]
    }}
  ]
}}

说明：
1）player_mark 必须是：详细的外貌 + 属性备注，不包含提示词标签，不包含 prompt，不包含合成说明，不包含结构标签
2）base_desc 必须是：场景基础描述，世界观 + 氛围 + 关键元素，不包含提示词结构，不包含负面提示词
3）scenes[].characters 必须是 characters[].player_name 的子集，如场景无人则为空数组 []
4）scene_type 必须是 "Indoor", "Outdoor" 或 "Special"
"""

    # --- Debug Logging Start ---
    if config.LLM_LOG:
        print("\\n" + "="*50)
        print(f" [LLM STORY Request] Provider: {llm_profile.provider} | Model: {model_name}")
        print("-" * 20 + " System Prompt " + "-" * 20)
        print(system_prompt.strip())
        print("-" * 20 + " User Prompt " + "-" * 20)
        print(user_prompt.strip())
        print("="*50 + "\\n")
    # --- Debug Logging End ---

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        
        # --- Debug Logging Start ---
        if config.LLM_LOG:
            print("\\n" + "="*50)
            print(" [LLM STORY Response]")
            print("-" * 20 + " Raw Content " + "-" * 20)
            print(content)
            print("="*50 + "\\n")
        # --- Debug Logging End ---
        
        usage = response.usage.model_dump() if response.usage else {}
        
        result = {}
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
        
        return result
            
    except Exception as e:
        raise Exception(f"OpenAI API Error ({llm_profile.provider}): {str(e)}")
