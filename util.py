import os
import json
import logging
import platform

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

	# setup commands - this needs to be moved to an external .conf
	cmd_move = ""
	if get_platform() == "windows":
		cmd_move = "move"
		cmd_copy = "copy"
	else:
		cmd_move = "mv"
		cmd_copy = "cp"

	params["cmd_move"] = cmd_move
	params["cmd_copy"] = cmd_copy

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

# if the file is not in the cache, return 0
# if the file is IN the cache and modified, return 1
# if the file is IN the cache, but not modified, return 2
def source_file_cache_status(path, cache):
	if path in cache:
		cached_modified = cache[path]
		modified = os.path.getmtime(path)
		if modified <= cached_modified:
			return 2
		else:
			return 1
	return 0

def strip_trailing_slash(path):
	if path[-1] == "/" or path[-1] == "\\":
		path = path[:-1]
	return path

def type_is_string(value):
	return type(value) is str or type(value) is unicode