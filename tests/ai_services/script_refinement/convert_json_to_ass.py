import json
import sys
from pathlib import Path

def format_ass_timestamp(seconds: float) -> str:
    """
    将秒数转换为 ASS 时间戳格式 (H:MM:SS.ss)
    例如: 6.4 -> 0:00:06.40
    """
    if seconds is None:
        seconds = 0.0

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centiseconds = int(round((seconds - int(seconds)) * 100))

    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"

ASS_HEADER_TEMPLATE = """[Script Info]
Title: Refined Script
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,55,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,30,1
Style: Comment,Arial,35,&H80CCCCCC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

def convert_to_ass(json_file_path: str, output_ass_path: str = None):
    """
    读取 JSON 文件并生成 ASS 字幕文件
    """
    input_path = Path(json_file_path)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return

    if output_ass_path is None:
        output_ass_path = input_path.with_suffix('.ass')

    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse JSON: {e}")
        return

    refined_script = data.get('refined_script', [])

    if not refined_script:
        print("Warning: No 'refined_script' found in JSON.")
        return

    ass_events = []
    dialogue_count = 0
    comment_count = 0

    for segment in refined_script:
        text = segment.get('refined_text')
        start_time = segment.get('start', 0.0)
        end_time = segment.get('end', 0.0)

        start_str = format_ass_timestamp(start_time)
        end_str = format_ass_timestamp(end_time)

        if text and segment.get('source_of_truth') != 'ASR_ONLY':
            # This is a valid dialogue line
            # Dialogue: 0,0:00:06.40,0:00:07.00,Default,,0,0,0,,快十二点了。
            event_line = f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}"
            ass_events.append(event_line)
            dialogue_count += 1
        elif segment.get('source_of_truth') == 'OCR_IGNORED':
            # This is a comment showing ignored noise
            ignored_text = segment.get('original_ocr') or segment.get('original_asr') or "IGNORED"
            # Replace newlines to prevent breaking ASS format
            ignored_text = ignored_text.replace('\n', '\\N')
            # Comment: 0,0:00:06.40,0:00:07.00,Comment,,0,0,0,,安然
            event_line = f"Comment: 0,{start_str},{end_str},Comment,,0,0,0,,{ignored_text}"
            ass_events.append(event_line)
            comment_count += 1

    # 写入文件
    output_path = Path(output_ass_path)
    # 确保父目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8-sig') as f: # Use utf-8-sig for better compatibility
        f.write(ASS_HEADER_TEMPLATE)
        f.write("\n".join(ass_events))

    print(f"Conversion complete!")
    print(f"Source: {input_path}")
    print(f"Output: {output_path}")
    print(f"Total Dialogue lines: {dialogue_count}")
    print(f"Total Comment lines (ignored noise): {comment_count}")

if __name__ == "__main__":
    print("=== JSON to ASS Converter for Script Refinement ===")
    if len(sys.argv) < 2:
        print("Usage: python convert_json_to_ass.py <path_to_json_file> [output_ass_path]")
        print("Example: python convert_json_to_ass.py result.json")
    else:
        json_file = sys.argv[1]
        ass_file = sys.argv[2] if len(sys.argv) > 2 else None
        convert_to_ass(json_file, ass_file)