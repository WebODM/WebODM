#!/bin/bash
__dirname=$(cd $(dirname "$0"); pwd -P)
cd ${__dirname}

usage(){
  echo "Usage: $0 <command>"
  echo
  echo "This program manages the background worker processes. WebODM requires at least one background process worker to be running at all times."
  echo 
  echo "Command list:"
  echo "	start				Start background worker"
  echo "	scheduler start		Start background worker scheduler"
  echo "	scheduler stop 		Stop background worker scheduler"
  exit
}

check_command(){
	check_msg_prefix="Checking for $1... "
	check_msg_result="\033[92m\033[1m OK\033[0m\033[39m"

	hash $1 2>/dev/null || not_found=true 
	if [[ $not_found ]]; then
		
		# Can we attempt to install it?
		if [[ ! -z "$3" ]]; then
			echo -e "$check_msg_prefix \033[93mnot found, we'll attempt to install\033[39m"
			run "$3 || sudo $3"

			# Recurse, but don't pass the install command
			check_command "$1" "$2"	
		else
			check_msg_result="\033[91m can't find $1! Check that the program is installed and that you have added the proper path to the program to your PATH environment variable before launching WebODM. If you change your PATH environment variable, remember to close and reopen your terminal. $2\033[39m"
		fi
	fi

	echo -e "$check_msg_prefix $check_msg_result"
	if [[ $not_found ]]; then
		return 1
	fi
}

environment_check(){
	check_command "celery" "Run \033[1msudo pip install -U celery\033[0m" "pip install -U celery"
	if [[ -z "$WO_BROKER" ]]; then
		echo -e "\033[91mWO_BROKER environment variable is not set. Defaulting to redis://localhost\033[39m"
		export WO_BROKER=redis://localhost
	fi

    # Only set if `WEB_CONCURRENCY` is not defined, allows overriding.
    # See: https://docs.gunicorn.org/en/latest/settings.html#workers
    if [ -z "$WEB_CONCURRENCY" ]; then
        export WEB_CONCURRENCY=$((2*$(nproc)+1))
    fi
}


start(){
	action=$1
	echo "Starting worker using broker at $WO_BROKER"
	python manage.py syncgrids
	celery -A worker worker --autoscale $WEB_CONCURRENCY,2 --max-tasks-per-child 1000 --loglevel=warning > /dev/null
}

start_scheduler(){
	stop_scheduler
	if [[ ! -f ./celerybeat.pid ]]; then
		celery -A worker beat &
	else
		echo "Scheduler already running (celerybeat.pid exists)."
	fi
}

stop_scheduler(){
	if [[ -f ./celerybeat.pid ]]; then
		kill -9 $(cat ./celerybeat.pid) 2>/dev/null
		rm ./celerybeat.pid 2>/dev/null
		echo "Scheduler has shutdown."
	else
		echo "Scheduler is not running."
	fi
}

if [[ $1 = "start" ]]; then
	environment_check
	start
elif [[ $1 = "scheduler" ]]; then
	if [[ $2 = "start" ]]; then
		environment_check
		start_scheduler
	elif [[ $2 = "stop" ]]; then
		environment_check
		stop_scheduler
	else
		usage
	fi
else
	usage
fi
