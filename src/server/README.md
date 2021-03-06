# electric server
Battery charger integration, information and provisioning server.  This is a python application
that exposes your charger information via a RESTful web server.

# what you'll need
To use this, you will need the following:
1. iCharger 308 DUO, 408 DUO or 4010 DUO
1. A mini-USB cable to connect the Raspberry PI3 to your iCharger 
1. A Raspberry PI 3

Please note: a Raspberry PI 2 WILL NOT suffice as this project uses Bluetooth BLE and WIFI, both
of which are present on the v3 PI and NOT on the v2 PI.

# running from the PyPi distribution
There are two ways to run the server - either from a module installed via PyPi, or via a
copy of the GitHub repo.

Install the server from PyPi, e.g.

    $ pip install electric

If you have already installed a previous version, use this variant instead

    $ pip install electric --upgrade

Then you can run it as a web service using the following command:

    $ electric-server

The web service runs on port 5000 - you have no choice.  Thank you for your co-operation.

# running from the github repo
Setup a virtualenv for the project, and load the required modules using the requirements.txt file

    $  pip install -r requirements.txt

Use the run_server.sh script within this directory to start the server.  This assumes your current python
environment has all the required modules installed of course.

# Setting up to run as a service on the Pi
- sudo su (probably)
- Copy the file `scripts/electric.service` to `/etc/systemd/system` on the Pi.
- Change permissions to 664, `chmod 664 /etc/systemd/system/electric.service`
- Run `systemctl daemon-reload` on the Pi.
- Run `systemctl start electric.service` on ze Pi.

# publish to pypi or pypitest repository
The server code can be published to the pypi repo as long as you have account credentials for the pypi
repository set up in your ~/.pypirc file.  See the pypirc_template for an example of this file. 

Note: for this to work properly you must install the Python GIT libraries by hand, as these are not
part of the normal release requirement they are handled differently.

  $ pip install -r dev_requirements.txt

The setup.py is generated from a template so that we can easily inject requirements and version information
into the file on any platform without having to duplicate information in two places. 

## example publishing to pypitest (the test environment)

    $ python scripts/distribute.py -v "0.6.8" -p -t
    
# PyCharm is warning me that the parent module isn't found while handling absolute imports
Check this link: https://youtrack.jetbrains.com/oauth?state=%2Fissue%2FPY-20171

specifically, the file here should replace the one you have installed: 
https://youtrack.jetbrains.com/_persistent/utrunner.py?file=74-332199&c=true
