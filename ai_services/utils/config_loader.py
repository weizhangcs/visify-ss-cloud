import yaml
import logging
from pathlib import Path
from typing import Dict, Any
from django.conf import settings
from functools import lru_cache

logger = logging.getLogger(__name__)

class AIConfigLoader:
    """
    单例配置加载器，用于加载 ai_inference_config.yaml。
    支持缓存，避免重复 IO 读取。
    """
    _instance = None
    _config_cache = None
    _config_path = Path(settings.BASE_DIR) / "ai_services" / "configs" / "ai_inference_config.yaml"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AIConfigLoader, cls).__new__(cls)
        return cls._instance

    def get_config(self, service_name: str = None) -> Dict[str, Any]:
        """
        获取完整配置或指定服务的配置。
        """
        if self._config_cache is None:
            self._load_config()
        
        if service_name:
            return self._config_cache.get(service_name, {})
        return self._config_cache

    def reload(self):
        """强制重新加载配置 (用于热更新场景)"""
        self._load_config()

    def _load_config(self):
        try:
            if not self._config_path.exists():
                logger.warning(f"Config file not found at {self._config_path}, using empty config.")
                self._config_cache = {}
                return

            with open(self._config_path, encoding='utf-8') as f:
                self._config_cache = yaml.safe_load(f) or {}
            logger.info(f"Loaded AI inference config from {self._config_path}")
        except Exception as e:
            logger.error(f"Failed to load AI config: {e}")
            self._config_cache = {}