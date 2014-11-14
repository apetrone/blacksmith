import os
import re
import copy
import json
import shlex
import logging
import platform
import subprocess

def clean_path(path):
	return strip_trailing_slash(path)

def recursive_update(root, params):
	for key, value in root.iteritems():
		if type_is_string(value):
			root[key] = value % params
		elif type(value) is dict:
			recursive_update(value, params)

def execute_commands(
	tools, 
	current_tool,
	paths,
	asset,
	target_path,
	platform_name,
	param_overrides = {}
	):
	lines = []


	#logging.info(current_tool.name)
	outputs = []
	for raw_command in current_tool.commands[platform_name]:
		params = generate_params_for_file(
			paths, 
			asset,
			target_path,
			platform_name
		)

		params.update(param_overrides)
		recursive_update(params, params)

		if type_is_string(raw_command):		
			try:
				cmd = (raw_command % params).encode("ascii")
				lines.append(cmd)
			except TypeError as exc:
				logging.error(raw_cmd)
				logging.error(params)			

			# we need this to pass to shlex, otherwise it could screw up
			# paths on non-posix compliant systems.
			use_posix_paths = (get_platform() is not "windows")
			runnable = shlex.split(cmd, posix=use_posix_paths)
			try:
				returncode = subprocess.call(runnable, shell=run_as_shell())
				if returncode != 0:
					logging.error("ERROR %s" % cmd)
			except OSError as exc:
				logging.error("ERROR executing \"%s\", %s" % (cmd, exc))
			
			# record the output as the absolute destination path
			outputs.append(current_tool.output % params)
			
		elif type(raw_command) is dict:
			if not "tool" in raw_command:
				raise Exception("Missing tool from command block! (%s)",
					current_tool.name
				)

			# dictionaries in commands are interpreted as tools.
			# get the tool name and use the params it provides
			# as overrides.
			subtool = tools[raw_command["tool"]]
			sub_overrides = {}
			if "params" in raw_command:
				sub_overrides = raw_command["params"]
			execute_commands(
				tools,
				subtool,
				paths,
				asset,
				target_path,
				platform_name,
				sub_overrides
			)

	return outputs

def generate_params_for_file(
		paths, 
		asset, 
		src_file_path,
		platform_name
	):
	# base parameters are from the asset block
	params = copy.copy(asset.params)

	for key, value in paths:
		params[key] = value

	# TODO: need to also take variables from root conf
	basename = os.path.basename(src_file_path)

	params["source_root"] = paths.source_root
	params["destination_root"] = paths.destination_root

	# default parameters
	params["src_file_relpath"] = os.path.relpath(src_file_path, paths.source_root)
	params["src_file_path"] = src_file_path
	params["src_file_basename"] = basename
	params["src_file_ext"] = \
		os.path.basename(src_file_path).split(".")[1]

	params["dst_file_path"] = os.path.join(
		paths.destination_root,
		asset.dst_folder,
		basename
	)
	params["dst_file_noext"] = os.path.join(
		paths.destination_root,
		asset.dst_folder,
		basename.split(".")[0]
	)

	params["abs_src_folder"] = asset.abs_src_folder
	params["abs_dst_folder"] = asset.abs_dst_folder

	params["host_platform"] = platform_name

	return params


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

def get_supported_platforms():
	return [
		"linux",
		"macosx",
		"windows"
	]

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
		if not path_list[key]:
			continue
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

def setup_environment(base_path, paths, target_platform):
	# replace variables
	vars = {
		"host_platform": get_platform(),
		"target_platform": target_platform,
		"source_root" : paths["source_root"]
	}

	old_paths = copy.copy(paths)
	paths = {}
	for path_name, path in old_paths.iteritems():
		for key, value in vars.iteritems():
			path = path.replace("${%s}" % key, value)
			paths[path_name] = path

	# normalize the paths; which makes them absolute from relative
	# and cleans up separators, etc.
	paths = normalize_paths(base_path, paths)

	# if "tool_path" in paths:
	# 	if type(paths["tool_path"]) is unicode:
	# 		paths["tool_path"] = [paths["tool_path"]]

	# 	tool_paths = ":".join(paths["tool_path"])
	# 	os.environ["PATH"] = os.environ["PATH"] + ":" + tool_paths

	return paths
def strip_trailing_slash(path):
	if path[-1] == "/" or path[-1] == "\\":
		path = path[:-1]
	return path

def type_is_string(value):
	return type(value) is str or type(value) is unicode