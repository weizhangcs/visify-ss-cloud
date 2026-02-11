import json
import sys
import os
from pathlib import Path

def format_timestamp(seconds: float) -> str:
    """
    将秒数转换为 SRT 时间戳格式 (HH:MM:SS,mmm)
    例如: 6.4 -> 00:00:06,400
    """
    if seconds is None:
        seconds = 0.0
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    
    # 处理毫秒进位
    if milliseconds >= 1000:
        milliseconds = 0
        secs += 1
        
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

def convert_to_srt(json_file_path: str, output_srt_path: str = None):
    """
    读取 JSON 文件并生成 SRT 字幕文件
    """
    input_path = Path(json_file_path)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return

    if output_srt_path is None:
        output_srt_path = input_path.with_suffix('.srt')
    
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse JSON: {e}")
        return

    # 兼容直接是列表或包含在 refined_script 字段中的情况
    if isinstance(data, list):
        refined_script = data
    else:
        refined_script = data.get('refined_script', [])

    if not refined_script:
        print("Warning: No 'refined_script' found in JSON.")
        return

    srt_lines = []
    counter = 1

    for segment in refined_script:
        text = segment.get('refined_text')
        
        # 核心逻辑：过滤掉 null 或空文本 (例如 OCR_IGNORED)
        if not text:
            continue
            
        start_time = segment.get('start', 0.0)
        end_time = segment.get('end', 0.0)
        
        # 格式化时间轴
        start_str = format_timestamp(start_time)
        end_str = format_timestamp(end_time)
        
        # 构建 SRT 块
        srt_lines.append(str(counter))
        srt_lines.append(f"{start_str} --> {end_str}")
        srt_lines.append(str(text)) # 确保是字符串
        srt_lines.append("") # 空行分隔
        
        counter += 1

    # 写入文件
    output_path = Path(output_srt_path)
    # 确保父目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(srt_lines))
    
    print(f"Conversion complete!")
    print(f"Source: {input_path}")
    print(f"Output: {output_path}")
    print(f"Total subtitles: {counter - 1}")

if __name__ == "__main__":
    print("=== JSON to SRT Converter for Script Refinement ===")
    if len(sys.argv) < 2:
        print("Usage: python convert_json_to_srt.py <path_to_json_file> [output_srt_path]")
        print("Example: python convert_json_to_srt.py result.json")
    else:
        json_file = sys.argv[1]
        srt_file = sys.argv[2] if len(sys.argv) > 2 else None
        convert_to_srt(json_file, srt_file)