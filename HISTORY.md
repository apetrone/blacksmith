## History

1.0.3 - July 10, 2013

	- Added include keyword to configuration files to import common configs into the active one.
		Only relative imports are assumed. Duplicate imports will be ignored.
	- Paths are now relative to the configuration file as opposed to the current working directory.

1.0.2 - June 12, 2013

	- Tools are now specified in a separate configuration file for better re-use.

1.0.1 - May 28, 2013

	- Added basic caching mechanism to reduce processing times for files that haven't changed.
	- Added OS command for file copies.

1.0.0 - May 9, 2012

	- Initial release.
