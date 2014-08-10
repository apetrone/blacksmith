import os
import json
import shlex
import logging
import platform
import subprocess

def clean_path(path):
	return strip_trailing_slash(path)

def generate_params_for_file(
		paths, 
		asset, 
		src_file_path,
		platform_name
	):
	# base parameters are from the asset block
	params = asset.params

	basename = os.path.basename(src_file_path)

	# default parameters
	params["src_file_path"] = src_file_path
	params["src_file_basename"] = basename
	params["src_file_ext"] = \
		os.path.basename(src_file_path).split(".")[1]

	params["dst_file_path"] = os.path.join(
		paths.compiled_assets,
		asset.dst_folder,
		basename
	)
	params["dst_file_noext"] = os.path.join(
		paths.compiled_assets,
		asset.dst_folder,
		basename.split(".")[0]
	)
	

	params["abs_src_folder"] = asset.abs_src_folder
	params["abs_dst_folder"] = asset.abs_dst_folder

	params["platform"] = platform_name

	return params

def execute_commands(tools, current_tool, params):
	lines = []

	for raw_command in current_tool.commands:
		try:
			cmd = (raw_command % params).encode("ascii")
			lines.append(cmd)
		except TypeError as exc:
			logging.error(raw_cmd)
			logging.error(params)			

		logging.info(cmd)
		runnable = shlex.split(cmd)
		try:
			returncode = subprocess.call(runnable, shell=run_as_shell())
			if returncode != 0:
				logging.error("ERROR %s" % cmd)
		except OSError as exc:
			logging.error("ERROR executing \"%s\", %s" % (cmd, exc))

def get_platform():
	p = platform.platform().lower()
	if "linux" in p:
		return "linux"
	elif "darwin" in p:
		return "macosx"	
	elif "nt" or "windows" in p:
		return "windows"
	else:
		return "unknown"


def load_tools(config_path, tools):
	""" load tools and treat tools as a path if it happens to be a string.
		Otherwise, return it, because it's not what we're expecting.
	"""
	if tools and type_is_string(tools):
		base_path = os.path.dirname(config_path)
		#logging.info( "base_path = %s" % base_path )
		#logging.info( "config.tools = %s" % config.tools )
		abs_tools_path = os.path.abspath(
			os.path.join(base_path, tools_path)
		)
		logging.info("Importing tools from %s..." % abs_tools_path)
		return load_config(abs_tools_path)

	return tools

def make_dirs(target_path, chmod=0775):
	try:
		os.makedirs(target_path, chmod)

	except OSError as exc:
		if exc.errno == 20:
			logging.error("Attempted to make a path: \"%s\", but ran "
				"into a file with the name of an expected directory." % path)
			logging.error("Check for files that have the same name of the "
				"directory you may want to create."
			)
			raise

		# OSError: [Errno 17] File exists:
		pass

	except:
		raise

def normalize_paths(base_path, path_list):
	paths = {}

	for key in path_list:
		if type_is_string(path_list[key]):
			value = clean_path(path_list[key])
			value = os.path.abspath(os.path.join(base_path, value))
		elif type(path_list[key]) is list:
			items = path_list[key]
			for path in items:
				path = clean_path(path)
				path = os.path.abspath(os.path.join(base_path,path))
			value = items
		else:
			raise Exception(
				"Unknown path type! key: %s -> %s" %
				(key, type(path_list[key]))
			)
		
		paths[key] = value

	return paths


def run_as_shell():
	is_shell = False
	if get_platform() == "windows":
		is_shell = True
	return is_shell

def setup_environment(paths):
	# add asset_path to PATH environment var
	if type(paths["tool_path"]) is unicode:
		paths["tool_path"] = [paths["tool_path"]]

	tool_paths = ":".join(paths["tool_path"])
	os.environ["PATH"] = os.environ["PATH"] + ":" + tool_paths

def strip_trailing_slash(path):
	if path[-1] == "/" or path[-1] == "\\":
		path = path[:-1]
	return path

def type_is_string(value):
	return type(value) is str or type(value) is unicode