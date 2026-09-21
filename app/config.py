from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env', override=False)


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv('RADAR_DATA_DIR', str(ROOT / 'data'))))
    deepseek_key: str = field(default_factory=lambda: os.getenv('DEEPSEEK_API_KEY', ''))
    deepseek_base: str = field(default_factory=lambda: os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/'))
    deepseek_model: str = field(default_factory=lambda: os.getenv('DEEPSEEK_MODEL', 'deepseek-flash'))
    fuyao_key: str = field(default_factory=lambda: os.getenv('FUYAO_API_KEY', ''))
    fuyao_key_file: str = field(default_factory=lambda: os.getenv('FUYAO_KEY_FILE', str(Path.home() / '.codex/secrets/fuyao-api-key')))
    ifind_script: str = field(default_factory=lambda: os.getenv('IFIND_SCRIPT', str(Path.home() / '.codex/skills/ifind-finance-data/call-node.js')))
    scheduler_enabled: bool = field(default_factory=lambda: os.getenv('RADAR_SCHEDULER', '1') == '1')
    allow_live: bool = field(default_factory=lambda: os.getenv('RADAR_ALLOW_LIVE', '1') == '1')
    ai_enabled: bool = field(default_factory=lambda: os.getenv('RADAR_AI_ENABLED', '1') == '1')
    session_secure: bool = field(default_factory=lambda: os.getenv('RADAR_SECURE_COOKIE', '0') == '1')
    max_tasks: int = 12
    max_total_tasks: int = 300
    request_timeout: float = 8.0
    llm_timeout: float = 35.0

    def read_fuyao_key(self) -> str:
        if self.fuyao_key:
            return self.fuyao_key
        try:
            return Path(self.fuyao_key_file).read_text().strip()
        except OSError:
            return ''
