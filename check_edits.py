import json
import os

log_path = r"C:\Users\tirth\.gemini\antigravity\brain\3c29bfff-ab49-418a-bd17-802274a995bf\.system_generated\logs\transcript.jsonl"
for i, line in enumerate(open(log_path, 'r', encoding='utf-8', errors='ignore')):
    if i > 375:
        break
    try:
        obj = json.loads(line)
        if not obj.get('tool_calls'):
            continue
        for tc in obj['tool_calls']:
            if tc.get('name') in ['replace_file_content', 'multi_replace_file_content', 'write_to_file']:
                args = tc.get('args', tc.get('parameters', {}))
                tf = args.get('TargetFile', '')
                instr = args.get('Instruction', args.get('Description', ''))
                print(f"Step {i:3d} | {tc['name']:22s} | {os.path.basename(tf):20s} | {instr[:60]}")
    except Exception as e:
        print(f"Error at {i}: {e}")
