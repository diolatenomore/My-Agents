import os
import yaml
from typing import Dict, List, Optional
from config.config import config

class Skill:
    """技能类"""
    
    def __init__(self, name: str, description: str, config: Dict):
        self.name = name
        self.description = description
        self.config = config
    
    def get_info(self) -> Dict:
        """获取技能信息"""
        return {
            "name": self.name,
            "description": self.description,
            "config": self.config
        }

class SkillRegistry:
    """技能注册表"""
    
    def __init__(self):
        self.skills: Dict[str, Skill] = {}
        self.skill_dir = config.get("skills.directory", "src/skills")
        self.extension = config.get("skills.extension", ".yaml")
        self.load_skills()
    
    def load_skills(self):
        """加载技能"""
        if not os.path.exists(self.skill_dir):
            return
        
        for filename in os.listdir(self.skill_dir):
            if filename.endswith(self.extension):
                skill_path = os.path.join(self.skill_dir, filename)
                try:
                    with open(skill_path, "r", encoding="utf-8") as f:
                        skill_config = yaml.safe_load(f)
                    name = skill_config.get("name", filename.replace(self.extension, ""))
                    description = skill_config.get("description", "")
                    self.skills[name] = Skill(name, description, skill_config)
                except Exception as e:
                    print(f"加载技能 {filename} 失败: {str(e)}")
    
    def get_skill(self, name: str) -> Optional[Skill]:
        """获取技能"""
        return self.skills.get(name)
    
    def list_skills(self) -> List[str]:
        """列出所有技能"""
        return list(self.skills.keys())
    
    def get_skill_info(self, name: str) -> Optional[Dict]:
        """获取技能信息"""
        skill = self.get_skill(name)
        if skill:
            return skill.get_info()
        return None