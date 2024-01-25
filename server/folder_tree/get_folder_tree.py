import os
import ast
import re
import sys
import json
from folder_tree_generator import generate_tree


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('OpenMates.*', 'OpenMates', full_current_path)
sys.path.append(main_directory)


def get_folder_tree():
    output_text = generate_tree(main_directory, ignore_file_path=main_directory+"/.gitignore")
    return output_text

if __name__ == "__main__":
    print(get_folder_tree())