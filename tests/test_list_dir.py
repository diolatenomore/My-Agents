from src.vfs.staging_area import StagingArea
from src.vfs.operations import list_dir

StagingArea.load("task987")
result = list_dir("/Users/tinklingowl/PycharmProjects/AI-Agents/workspace/system_files")
print(result)