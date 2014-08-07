import os
import logging
import platform

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