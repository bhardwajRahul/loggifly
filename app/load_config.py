from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
    ConfigDict,
    SecretStr,
    ValidationError
)
from enum import Enum
from typing import Dict, List, Optional, Union
import os
import logging
import copy
import yaml

logging.getLogger(__name__)

"""
This module handles configuration loading and validation using Pydantic models. 
YAML configuration is loaded first, then environment variables are merged in, allowing environment variables to override YAML values, and YAML to override defaults. 
The merged configuration is validated with Pydantic. Legacy config formats are migrated for compatibility.
"""

def validate_priority(v):
    """
    Validate and normalize the priority value for notifications. Accepts both string and integer representations.
    Returns a valid priority or the default if invalid.
    """
    if isinstance(v, str):
        try:
            v = int(v)
        except ValueError:
            pass
    if isinstance(v, int):
        if not 1 <= int(v) <= 5:
            logging.warning(f"Error in config for ntfy.priority. Must be between 1-5, '{v}' is not allowed. Using default: '3'")
            return 3
    if isinstance(v, str):
        options = ["max", "urgent", "high", "default", "low", "min"]
        if v not in options:
            logging.warning(f"Error in config for ntfy.priority:'{v}'. Only 'max', 'urgent', 'high', 'default', 'low', 'min' are allowed. Using default: '3'")
            return 3
    return v

class BaseConfigModel(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_default=True, use_enum_values=True)


class ExcludedKeywords(BaseConfigModel):
    keyword: Optional[str] = None
    regex: Optional[str] = None

class Settings(BaseConfigModel):    
    """
    Application-wide settings for logging, notifications, and feature toggles.
    """
    log_level: str = Field("INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)")
    multi_line_entries: bool = Field(True, description="Enable multi-line log detection")
    disable_start_message: bool = Field(False, description="Disable startup notification")
    disable_shutdown_message: bool = Field(False, description="Disable shutdown notification")
    disable_config_reload_message: bool = Field(False, description="Disable config reload notification")
    disable_container_event_message: bool = Field(False, description="Disable notification on container stops/starts")
    reload_config: bool = Field(True, description="Disable config reaload on config change")
    
    # modular settings:
    attach_logfile: bool = Field(False, description="Attach logfile to notification")
    notification_cooldown: int = Field(5, description="Cooldown in seconds for repeated alerts")
    notification_title: str = Field("default", description="Set a template for the notification title")
    action_cooldown: Optional[int] = Field(300)
    attachment_lines: int = Field(20, description="Number of log lines to include in attachments")
    hide_regex_in_title: Optional[bool] = Field(False, description="Hide the regex in the notification title")
    excluded_keywords: Optional[List[Union[str, ExcludedKeywords]]] = Field(default=None, description="List of keywords to exclude from notifications")

class ModularSettings(BaseConfigModel):
    """
    Optional settings that can be overridden per keyword or container.
    """
    ntfy_tags: Optional[str] = None
    ntfy_topic: Optional[str] = None
    ntfy_priority: Optional[int] = None
    ntfy_url: Optional[str] = None
    ntfy_token: Optional[SecretStr] = None
    ntfy_username: Optional[str] = None
    ntfy_password: Optional[SecretStr] = None
    apprise_url: Optional[SecretStr] = None
    webhook_url: Optional[str] = None
    webhook_headers: Optional[dict] = None

    attachment_lines: Optional[int] = None
    notification_cooldown: Optional[int] = None
    notification_title: Optional[str] = None
    action_cooldown: Optional[int] = None
    attach_logfile: Optional[bool] = None
    excluded_keywords: Optional[List[Union[str, ExcludedKeywords]]] = Field(default=None, description="List of keywords to exclude from notifications")
    hide_regex_in_title: Optional[bool] = None

class ActionEnum(str, Enum):
    RESTART = "restart"
    STOP = "stop"



class RegexItem(ModularSettings):
    """
    Model for a regex-based keyword with optional settings.
    """
    regex: str
    json_template: Optional[str] = None
    template: Optional[str] = None
    action: Optional[ActionEnum] = None

class KeywordItem(ModularSettings):
    """
    Model for a string-based keyword with optional settings.
    """
    keyword: str
    json_template: Optional[str] = None
    action: Optional[ActionEnum] = None

class KeywordBase(BaseModel):
    """
    Base model for keyword lists, with pre-validation to handle legacy and misconfigured entries.
    """
    keywords: List[Union[str, KeywordItem, RegexItem]] = []

    @model_validator(mode="before")
    def int_to_string(cls, values):
        """
        Convert integer keywords to strings and filter out misconfigured entries before validation.
        """
        for field in ["keywords", "keywords_with_attachment"]:
            if field in values and isinstance(values[field], list):
                converted = []
                for kw in values[field]:
                    if isinstance(kw, dict):
                        keys = list(kw.keys())
                        if not any(key in keys for key in ["keyword", "regex"]):
                            logging.warning(f"Ignoring Error in config in field '{field}': '{kw}'. You have to set 'keyword' or 'regex' as a key.")
                            continue
                        for key in keys:
                            if isinstance(kw[key], int):
                                kw[key] = str(kw[key])
                        converted.append(kw)
                    else:
                        try:
                            converted.append(str(kw))
                        except ValueError:
                            logging.warning(f"Ignoring unexpected Error in config in field '{field}': '{kw}'.")
                            continue
                values[field] = converted
        return values
    
class ContainerConfig(KeywordBase, ModularSettings):    
    """
    Model for per-container configuration, including keywords and setting overrides.
    """
    hosts: Optional[str] = Field(default=None, description="The host in which the container should be monitored") 

    _validate_priority = field_validator("ntfy_priority", mode="before")(validate_priority)

class GlobalKeywords(BaseConfigModel, KeywordBase):
    pass

class NtfyConfig(BaseConfigModel):
    url: str = Field(..., description="Ntfy server URL")
    topic: str = Field(..., description="Ntfy topic name")
    token: Optional[SecretStr] = Field(default=None, description="Optional access token")
    username: Optional[str] = Field(default=None, description="Optional username")
    password: Optional[SecretStr] = Field(default=None, description="Optional password")
    priority: Optional[Union[str, int]] = Field(default=3, description="Message priority 1-5")
    tags: Optional[str] = Field("kite,mag", description="Comma-separated tags")

    _validate_priority = field_validator("priority", mode="before")(validate_priority)

class AppriseConfig(BaseConfigModel):  
    url: SecretStr = Field(..., description="Apprise compatible URL")

class WebhookConfig(BaseConfigModel):
    url: str
    headers: Optional[dict] = Field(default=None)

class NotificationsConfig(BaseConfigModel):
    ntfy: Optional[NtfyConfig] = Field(default=None, validate_default=False)
    apprise: Optional[AppriseConfig] = Field(default=None, validate_default=False)
    webhook: Optional[WebhookConfig] = Field(default=None, validate_default=False)

    @model_validator(mode="after")
    def check_at_least_one(self) -> "NotificationsConfig":
        if self.ntfy is None and self.apprise is None and self.webhook is None:
            logging.warning("You haven't configured any notification services. Notifications will not be sent.")
        return self

class GlobalConfig(BaseConfigModel):
    """Root configuration model for the application"""
    containers: Optional[Dict[str, ContainerConfig]] = Field(default=None)
    swarm_services: Optional[Dict[str, ContainerConfig]] = Field(default=None)
    global_keywords: GlobalKeywords
    notifications: NotificationsConfig
    settings: Settings

    @model_validator(mode="before")
    def transform_legacy_format(cls, values):
        """Migrate legacy list-based container definitions to dictionary format."""
        # Convert list containers to dict format
        for container_object in ["containers", "swarm_services"]:
            if isinstance(values.get(container_object), list):
                values[container_object] = {name: {} for name in values[container_object]}
            for container in values.get(container_object, {}):
                if isinstance(values.get(container_object).get(container), list):
                    values[container_object][container] = {
                        "keywords": values[container_object][container],
                    }
                elif values.get(container_object).get(container) is None:
                    values[container_object][container] = {
                        "keywords": [],
                    }
        return values
    
    @model_validator(mode="after")
    def check_at_least_one(self) -> "GlobalConfig":
        # Ensure at least one container or swarm service and at least one keyword is configured
        if not self.containers and not self.swarm_services:
            raise ValueError("You have to configure at least one container")
        tmp_list = self.global_keywords.keywords.copy()
        if not tmp_list:
            if self.containers:
                for c in self.containers:
                    tmp_list.extend(self.containers[c].keywords)
            if self.swarm_services:
                for c in self.swarm_services:
                    tmp_list.extend(self.swarm_services[c].keywords)
        if not tmp_list:
            raise ValueError("No keywords configured. You have to set keywords either per container or globally.")
        return self
    

def format_pydantic_error(e: ValidationError) -> str:
    """Format Pydantic validation errors for user-friendly display."""
    error_messages = []
    for error in e.errors():
        location = ".".join(map(str, error["loc"]))
        msg = error["msg"]
        msg = msg.split("[")[0].strip()
        error_messages.append(f"Field '{location}': {msg}")
    return "\n".join(error_messages)


def prettify_config(data):
    """Recursively format config dict for display, masking secrets and ordering keys for readability."""
    if isinstance(data, dict):
        priority_keys = [k for k in ("regex", "keyword") if k in data]
        if priority_keys:
            rest_keys = [k for k in data.keys() if k not in priority_keys]
            ordered_dict = {k: data[k] for k in priority_keys + rest_keys}
            return {k: prettify_config(v) for k, v in ordered_dict.items()}
        return {k: prettify_config(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [prettify_config(item) for item in data]
    elif isinstance(data, SecretStr):
        return "**********"  
    else:
        return data

def convert_legacy_formats(config):
    """
    Migrate legacy configuration fields (e.g., keywords_with_attachment, action_keywords) to the current format.
    """
    def _migrate_keywords(legacy, new, new_field):
        new_key, new_value = new_field
        for item in legacy:
            if isinstance(item, (str, int)):
                new.append({"keyword": str(item), new_key: new_value})
            elif isinstance(item, dict):
                item[new_key] = new_value
                new.append(item)
    
    config_copy = copy.deepcopy(config)
    global_kw = config_copy.get("global_keywords", {})
    global_with_attachment = global_kw.pop("keywords_with_attachment", None)
    if global_with_attachment is not None:
        config_copy["global_keywords"].setdefault("keywords", [])
        _migrate_keywords(global_with_attachment, config_copy["global_keywords"]["keywords"], ("attach_logfile", True))
    
    for container_object in ["containers", "swarm_services"]:
        if container_object not in config_copy:
            continue
        for container_config in config_copy.get(container_object, {}).values():
            if container_config is None:
                continue
            container_config.setdefault("keywords", [])
            keywords_with_attachment = container_config.pop("keywords_with_attachment", None)
            if keywords_with_attachment is not None:
                _migrate_keywords(keywords_with_attachment, container_config["keywords"], ("attach_logfile", True))
            
            action_keywords = container_config.pop("action_keywords", None)
            if action_keywords is not None:
                for item in action_keywords:
                    if isinstance(item, dict):
                        if "restart" in item:
                            action = "restart"
                        elif "stop" in item:
                            action = "stop"
                        else:
                            action = None 
                        if action:
                            keyword = item[action]
                            if isinstance(keyword, dict) and "regex" in keyword:
                                container_config["keywords"].append({"regex": keyword["regex"], "action": action})
                            elif isinstance(keyword, str):
                                container_config["keywords"].append({"keyword": keyword, "action": action})
    return config_copy


def merge_yaml_and_env(yaml, env_update):
    """
    Recursively merge environment variable config into YAML config, overriding YAML values where present in env_update.
    """
    for key, value in env_update.items():
        if isinstance(value, dict) and key in yaml and key != {}:
            merge_yaml_and_env(yaml[key],value)
        else:
            if value is not None :
                yaml[key] = value
    return yaml


def load_config(official_path="/config/config.yaml"):
    """
    Load, merge, and validate the application configuration from YAML and environment variables.
    Returns the validated config object and the path used.
    """
    config_path = None
    required_keys = ["notifications", "settings", "global_keywords"]
    yaml_config = None
    legacy_path = "/app/config.yaml"
    paths = [official_path, legacy_path]
    for path in paths: 
        logging.debug(f"Trying path: {path}")
        if os.path.isfile(path):
            try:
                with open(path, "r") as file:
                    yaml_config = yaml.safe_load(file)
                    config_path = path
                    break
            except FileNotFoundError:
                logging.info(f"Error loading the config.yaml file from {path}")
            except yaml.YAMLError as e:
                logging.error(f"Error parsing the YAML file: {e}")
            except Exception as e:
                logging.error(f"Unexpected error loading the config.yaml file: {e}")
        else:
            logging.debug(f"The path {path} does not exist.")

    if yaml_config is None:
        logging.warning(f"The config.yaml could not be loaded.")
        yaml_config = {}
    else:
        logging.info(f"The config.yaml file was found in {config_path}.")

    for key in required_keys:
        if key not in yaml_config or yaml_config[key] is None:
            yaml_config[key] = {}

    """
    Load configuration values from environment variables, returning a config dict compatible with the YAML structure.
    """
    env_config = { "notifications": {}, "settings": {}, "global_keywords": {}}
    settings_values = {
        "log_level": os.getenv("LOG_LEVEL"),
        "attachment_lines": os.getenv("ATTACHMENT_LINES"),
        "multi_line_entries": os.getenv("MULTI_LINE_ENTRIES"),
        "notification_cooldown": os.getenv("NOTIFICATION_COOLDOWN"),
        "notification_title": os.getenv("NOTIFICATION_TITLE"),
        "reload_config": False if config_path is None else os.getenv("RELOAD_CONFIG"), 
        "disable_start_message": os.getenv("DISABLE_START_MESSAGE"),
        "disable_restart_message": os.getenv("DISABLE_CONFIG_RELOAD_MESSAGE"),
        "disable_shutdown_message": os.getenv("DISABLE_SHUTDOWN_MESSAGE"),
        "disable_container_event_message": os.getenv("DISABLE_CONTAINER_EVENT_MESSAGE"),
        "action_cooldown": os.getenv("ACTION_COOLDOWN"),
        "attach_logfile": os.getenv("ATTACH_LOGFILE", "false").lower() == "true",
        "hide_regex_in_title": os.getenv("HIDE_REGEX_IN_TITLE", "false").lower() == "true",
        "excluded_keywords": [kw.strip() for kw in os.getenv("EXCLUDED_KEYWORDS", "").split(",") if kw.strip()] if os.getenv("EXCLUDED_KEYWORDS") else None
        } 
    ntfy_values =  {
        "url": os.getenv("NTFY_URL"),
        "topic": os.getenv("NTFY_TOPIC"),
        "token": os.getenv("NTFY_TOKEN"),
        "priority": os.getenv("NTFY_PRIORITY"),
        "tags": os.getenv("NTFY_TAGS"),
        "username": os.getenv("NTFY_USERNAME"),
        "password": os.getenv("NTFY_PASSWORD")
        }
    webhook_values = {
        "url": os.getenv("WEBHOOK_URL"),
        "headers":os.getenv("WEBHOOK_HEADERS")
    }
    apprise_values = {
        "url": os.getenv("APPRISE_URL")
    }
    global_keywords_values = {
        "keywords": [kw.strip() for kw in os.getenv("GLOBAL_KEYWORDS", "").split(",") if kw.strip()] if os.getenv("GLOBAL_KEYWORDS") else [],
        "keywords_with_attachment": [kw.strip() for kw in os.getenv("GLOBAL_KEYWORDS_WITH_ATTACHMENT", "").split(",") if kw.strip()] if os.getenv("GLOBAL_KEYWORDS_WITH_ATTACHMENT") else [],
    }
    # Fill env_config dict with environment variables if they are set
    if os.getenv("CONTAINERS"):
        env_config["containers"] = {}
        for c in os.getenv("CONTAINERS", "").split(","):
            c = c.strip()
            env_config["containers"][c] = {}

    if os.getenv("SWARM_SERVICES"):
        env_config["swarm_services"] = {}
        for s in os.getenv("SWARM_SERVICES", "").split(","):
            s = s.strip()
            env_config["swarm_services"][s] = {}

    if any(ntfy_values.values()):
        env_config["notifications"]["ntfy"] = ntfy_values
        yaml_config["notifications"]["ntfy"] = {} if yaml_config["notifications"].get("ntfy") is None else yaml_config["notifications"]["ntfy"]

    if apprise_values["url"]: 
        env_config["notifications"]["apprise"] = apprise_values

    if webhook_values.get("url"):
        env_config["notifications"]["webhook"] = webhook_values
        yaml_config["notifications"]["webhook"] = {} if yaml_config["notifications"].get("webhook") is None else yaml_config["notifications"]["webhook"]

    for k, v in global_keywords_values.items():
        if v:
            env_config["global_keywords"][k]= v

    for key, value in settings_values.items(): 
        if value is not None:
            env_config["settings"][key] = value

    # Merge environment variables and yaml config
    merged_config = merge_yaml_and_env(yaml_config, env_config)
    merged_config = convert_legacy_formats(merged_config)
    # Validate the merged configuration with Pydantic
    config = GlobalConfig.model_validate(merged_config)

    config_dict = prettify_config(config.model_dump(exclude_none=True, exclude_defaults=False, exclude_unset=False))
    yaml_output = yaml.dump(config_dict, default_flow_style=False, sort_keys=False, indent=4)
    logging.info(f"\n ------------- CONFIG ------------- \n{yaml_output}\n ----------------------------------")

    return config, config_path

