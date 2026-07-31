import json
import os

log_path = r"C:\Users\tirth\.gemini\antigravity\brain\3c29bfff-ab49-418a-bd17-802274a995bf\.system_generated\logs\transcript.jsonl"
seen = set()

with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        try:
            obj = json.loads(line)
            if not obj.get('tool_calls'):
                continue
            for tc in obj['tool_calls']:
                if tc.get('name') == 'write_to_file':
                    args = tc.get('args', tc.get('parameters', {}))
                    tf = args.get('TargetFile', '')
                    clean_tf = tf.strip('\"\'').replace('\\\\', '\\')
                    if not clean_tf or 'brain' in clean_tf or clean_tf in seen:
                        continue
                    seen.add(clean_tf)
                    code = args.get('CodeContent', '')
                    if isinstance(code, str) and code.startswith('"') and code.endswith('"'):
                        try:
                            code = json.loads(code)
                        except Exception:
                            pass
                    os.makedirs(os.path.dirname(clean_tf), exist_ok=True)
                    with open(clean_tf, 'w', encoding='utf-8') as out:
                        out.write(code)
                    print(f"Restored cleanly: {clean_tf}")
        except Exception as e:
            continue
