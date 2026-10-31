#!/usr/bin/env bash
set -eo pipefail
__dirname=$(cd "$(dirname "$0")"; pwd -P)
cd "${__dirname}"

platform="Linux" # Assumed
uname=$(uname)
case $uname in
	"Darwin")
	platform="MacOS / OSX"
	;;
	MINGW*)
	platform="Windows"
	;;
esac

if [[ $platform = "Windows" ]]; then
	export COMPOSE_CONVERT_WINDOWS_PATHS=1
fi

dev_mode=false
gpu=false

# define realpath replacement function
if [[ $platform = "MacOS / OSX" ]]; then
    realpath() {
        [[ $1 = /* ]] && echo "$1" || echo "$PWD/${1#./}"
    }
fi

# Load default values
source "${__dirname}/.env"
DEFAULT_PORT="$WO_PORT"
DEFAULT_HOST="$WO_HOST"
DEFAULT_MEDIA_DIR="$WO_MEDIA_DIR"
DEFAULT_DB_DIR="$WO_DB_DIR"
DEFAULT_NODE_DIR="$WO_NODE_DIR"
DEFAULT_SSL="$WO_SSL"
DEFAULT_SSL_INSECURE_PORT_REDIRECT="$WO_SSL_INSECURE_PORT_REDIRECT"
DEFAULT_BROKER="$WO_BROKER"
DEFAULT_NODES="$WO_DEFAULT_NODES"

# Parse args for overrides
POSITIONAL=()
while [[ $# -gt 0 ]]
do
key="$1"

case $key in
    --port)
    export WO_PORT="$2"
    shift # past argument
    shift # past value
    ;;
    --hostname)
    export WO_HOST="$2"
    shift # past argument
    shift # past value
    ;;
    --media-dir)
    WO_MEDIA_DIR=$(realpath "$2")
    export WO_MEDIA_DIR
    shift # past argument
    shift # past value
    ;;
    --db-dir)
    WO_DB_DIR=$(realpath "$2")
    export WO_DB_DIR
    shift # past argument
    shift # past value
    ;;
    --node-dir)
    WO_NODE_DIR=$(realpath "$2")
    export WO_NODE_DIR
    shift # past argument
    shift # past value
    ;;
    --ssl)
    export WO_SSL=YES
    shift # past argument
    ;;
    --ssl-key)
    WO_SSL_KEY=$(realpath "$2")
    export WO_SSL_KEY
    shift # past argument
    shift # past value
    ;;
    --ssl-cert)
    WO_SSL_CERT=$(realpath "$2")
    export WO_SSL_CERT
    shift # past argument
    shift # past value
    ;;
    --ssl-insecure-port-redirect)
    export WO_SSL_INSECURE_PORT_REDIRECT="$2"
    shift # past argument
    shift # past value
    ;;
    --debug)
    export WO_DEBUG=YES
    shift # past argument
    ;;
    --dev-watch-plugins)
    export WO_DEV_WATCH_PLUGINS=YES
    shift # past argument
    ;;
    --dev)
    export WO_DEBUG=YES
    export WO_DEV=YES
    dev_mode=true
    shift # past argument
    ;;
    --gpu)
    gpu=true
    shift # past argument
    ;;
    --broker)
    export WO_BROKER="$2"
    shift # past argument
    shift # past value
    ;;
    --no-default-node)
    echo "ATTENTION: --no-default-node is deprecated. Use --default-nodes instead."
    export WO_DEFAULT_NODES=0
    shift # past argument
    ;;
    --with-micmac)
    load_micmac_node=true
    shift # past argument
    ;;
    --detached)
    detached=true
    shift # past argument
    ;;
    --default-nodes)
    export WO_DEFAULT_NODES="$2"
    shift # past argument
    shift # past value
    ;;
    --settings)
    WO_SETTINGS=$(realpath "$2")
    export WO_SETTINGS
    shift # past argument
    shift # past value
    ;;    
    --worker-memory)
    WO_WORKER_MEMORY="$2"
    export WO_WORKER_MEMORY
    shift # past argument
    shift # past value
    ;;	
    --worker-cpus)
    WO_WORKER_CPUS="$2"
    export WO_WORKER_CPUS
    shift # past argument
    shift # past value
    ;;
    --ipv6)
    ipv6=true
    export WO_IPV6=YES
    shift # past argument
    ;;
    *)    # unknown option
    POSITIONAL+=("$1") # save it in an array for later
    shift # past argument
    ;;
esac
done
set -- "${POSITIONAL[@]}" # restore positional parameter

if [[ "${WO_DEFAULT_NODES}" -gt 1 ]]; then
	echo "ATTENTION: --default-nodes values greater than 1 are no longer supported."
	export WO_DEFAULT_NODES="1"
fi

usage(){
  echo "Usage: $0 <command>"
  echo
  echo "This program helps to manage the setup/teardown of the docker containers for running WebODM. We recommend that you read the full documentation of docker at https://docs.docker.com if you want to customize your setup."
  echo
  echo "Command list:"
  echo "	start [options]		Start WebODM"
  echo "	stop			Stop WebODM"
  echo "	down			Stop and remove WebODM's docker containers"
  echo "	update			Update WebODM to the latest release"
  echo "	liveupdate		Update WebODM to the latest release without stopping it"
  echo "	rebuild			Rebuild all docker containers and perform cleanups"
  echo "	checkenv		Do an environment check and install missing components"
  echo "	test [frontend|backend] [args]	Run tests (all tests, or just frontend/backend with optional arguments)"
  echo "	resetadminpassword \"<new password>\"	Reset the administrator's password to a new one. WebODM must be running when executing this command and the password must be enclosed in double quotes."
  echo ""
  echo "Options:"
  echo "	--port	<port>	Set the port that WebODM should bind to (default: $DEFAULT_PORT)"
  echo "	--hostname	<hostname>	Set the hostname that WebODM will be accessible from (default: $DEFAULT_HOST)"
  echo "	--media-dir	<path>	Path where processing results will be stored to (default: $DEFAULT_MEDIA_DIR (docker named volume))"
  echo "	--db-dir	<path>	Path where the Postgres db data will be stored to (default: $DEFAULT_DB_DIR (docker named volume))"
  echo "	--node-dir	<path>	Path where temporary files will be stored during processing when using the default node (default: docker container storage)"
  echo "	--default-nodes	Whether to create a processing node attached to WebODM on startup (default: $DEFAULT_NODES)"
  echo "	--with-micmac	Create a NodeMICMAC node attached to WebODM on startup. Experimental! (default: disabled)"
  echo "	--ssl	Enable SSL and automatically request and install a certificate from letsencrypt.org. (default: $DEFAULT_SSL)"
  echo "	--ssl-key	<path>	Manually specify a path to the private key file (.pem) to use with nginx to enable SSL (default: None)"
  echo "	--ssl-cert	<path>	Manually specify a path to the certificate file (.pem) to use with nginx to enable SSL (default: None)"
  echo "	--ssl-insecure-port-redirect	<port>	Insecure port number to redirect from when SSL is enabled (default: $DEFAULT_SSL_INSECURE_PORT_REDIRECT)"
  echo "	--debug	Enable debug for development environments (default: disabled)"
  echo "	--dev	Enable development mode. In development mode you can make modifications to WebODM source files and changes will be reflected live. (default: disabled)"
  echo "	--dev-watch-plugins	Automatically build plugins while in dev mode. (default: disabled)"
  echo "	--broker	Set the URL used to connect to the celery broker (default: $DEFAULT_BROKER)"
  echo "	--detached	Run WebODM in detached mode. This means WebODM will run in the background, without blocking the terminal (default: disabled)"
  echo "	--gpu	Use GPU NodeODM nodes (Linux only) (default: disabled)"
  echo "	--settings	Path to a settings.py file to enable modifications of system settings (default: None)"
  echo "	--worker-memory	Maximum amount of memory allocated for the worker process (default: unlimited)"
  echo "	--worker-cpus	Maximum number of CPUs allocated for the worker process (default: all)"
  echo "	--ipv6	Enable IPV6"
  
  exit
}

detect_gpus(){
	# export GPU_AMD=false
	export GPU_NVIDIA=false

	if [ "${platform}" = "Linux" ]; then
		set +e
		if lspci | grep 'NVIDIA'; then
			echo "GPU_NVIDIA has been found"
			export GPU_NVIDIA=true
			set -e
			return
		fi

		if lspci | grep "VGA.*NVIDIA"; then
			echo "GPU_NVIDIA has been found"
			export GPU_NVIDIA=true
			set -e
			return
		fi
		NVIDIA_DEVICE=$(nvidia-smi -L | grep "GPU 0:" | awk -F ': ' '{print $2}' | awk -F '(' '{print $1}')
		#IF the NVIDIA_DEVICE has the word NVIDIA in it, then enable NVIDIA
		if [[ $NVIDIA_DEVICE == *"NVIDIA"* ]]; then
			echo "GPU_NVIDIA has been found"
			export GPU_NVIDIA=true
			set -e
			return
		fi

		# Total guess.  Need to look into AMD.
		# if lspci | grep "VGA.*AMD"; then
		# 	echo "GPU_AMD has been found"
		# 	export GPU_AMD=true
		# 	set -e
		# 	return
		# fi

		# if ! $GPU_NVIDIA && ! $GPU_AMD; then
		if ! $GPU_NVIDIA; then
			echo "Warning: GPU use was requested, but no GPU has been found"
			set -e
		fi
	else
		echo "Warning: GPU support is not available for $platform"
	fi
}

if [[ $gpu = true ]]; then
	detect_gpus
fi

docker_compose="docker-compose"
check_docker_compose(){
	dc_msg_ok="\033[92m\033[1m OK\033[0m\033[39m"

	# Check if docker-compose exists
	hash "docker-compose" 2>/dev/null || not_found=true
	if [[ $not_found ]]; then
		# Check if compose plugin is installed
		if ! docker compose > /dev/null 2>&1; then

			if [ "${platform}" = "Linux" ] && [ -z "$1" ] && [ ! -z "$HOME" ]; then
				echo -e "Checking for docker compose... \033[93mnot found, we'll attempt to install it\033[39m"
				check_command "curl" "Cannot automatically install docker compose. Please visit https://docs.docker.com/compose/install/" "" "silent"
				DOCKER_CONFIG=${DOCKER_CONFIG:-$HOME/.docker}
				mkdir -p $DOCKER_CONFIG/cli-plugins
				curl -SL# https://github.com/docker/compose/releases/download/v2.17.2/docker-compose-linux-x86_64 -o $DOCKER_CONFIG/cli-plugins/docker-compose
				chmod +x $DOCKER_CONFIG/cli-plugins/docker-compose
				check_docker_compose "y"
			else
				if [ -z "$1" ]; then
					echo -e "Checking for docker compose... \033[93mnot found, please visit https://docs.docker.com/compose/install/ to install docker compose\033[39m"
				else
					echo -e "\033[93mCannot automatically install docker compose. Please visit https://docs.docker.com/compose/install/\033[39m"
				fi
				return 1
			fi
		else
			docker_compose="docker compose"
		fi
	else
		docker_compose="docker-compose"
	fi

	if [ -z "$1" ]; then
		echo -e "Checking for $docker_compose... $dc_msg_ok"
	fi
}

# $1 = command | $2 = help_text | $3 = install_command (optional) | $4 = silent
check_command(){
	check_msg_prefix="Checking for $1... "
	check_msg_result="\033[92m\033[1m OK\033[0m\033[39m"
	unset not_found
	hash "$1" 2>/dev/null || not_found=true
	if [[ $not_found ]]; then

		# Can we attempt to install it?
		if [[ -n "$3" ]]; then
			echo -e "$check_msg_prefix \033[93mnot found, we'll attempt to install\033[39m"
			run "$3 || sudo $3"

			# Recurse, but don't pass the install command
			check_command "$1" "$2"
		else
			check_msg_result="\033[91m can't find $1! Check that the program is installed and that you have added the proper path to the program to your PATH environment variable before launching WebODM. If you change your PATH environment variable, remember to close and reopen your terminal. $2\033[39m"
		fi
	fi

	if [ -z "$4" ]; then
		echo -e "$check_msg_prefix $check_msg_result"
	fi

	if [[ $not_found ]]; then
		return 1
	fi
}

environment_check(){
    if [[ $WO_DEBUG = "YES" ]]; then
        local DOCKER_VERSION
        local COMPOSE_VERSION
        local MEDIA_DIR_OWNER
        local DB_DIR_OWNER
        echo "Host environment: $OSTYPE"
        if [[ "$(groups)" == *"docker"* ]]; then
            echo "You are in the docker group"
        else
            echo "You are not in the docker group"
        fi
    fi
    
    check_command "docker" "https://www.docker.com/"
    check_docker_compose

    if [[ $WO_DEBUG = "YES" ]]; then
        if [ -d $WO_MEDIA_DIR ]; then
            MEDIA_DIR_OWNER=$(stat -c "%U" $WO_MEDIA_DIR)
            if [[ $MEDIA_DIR_OWNER != $(whoami) ]]; then
                echo "You do not own the media directory. It is owned by $MEDIA_DIR_OWNER."
            fi
        fi
        if [ -d $WO_DB_DIR ]; then
            DB_DIR_OWNER=$(stat -c "%U" $WO_DB_DIR)
            if [[ $DB_DIR_OWNER != $(whoami) ]]; then
                echo "You do not own the database directory. It is owned by $DB_DIR_OWNER."
            fi

        fi
        DOCKER_VERSION=$(docker --version)
        # remove stderr in case podman throws complaints, ensure only compose ver is taken
        COMPOSE_VERSION=$($docker_compose version 2> /dev/null | head -n 1)
        echo "Docker version: $DOCKER_VERSION"
        echo "Compose version: $COMPOSE_VERSION"
        if [ -z "$DOCKER_HOST" ]; then
            echo "DOCKER_HOST is unset"
            if [[ "$($docker_compose -v)" != "podman"* ]] && [[ "$DOCKER_VERSION" == "podman"* ]]; then
                echo "You seem to be using podman with docker-compose instead of podman-compose. The above variable may need to be set, see https://docs.webodm.org/tutorials/using-podman/ for more information."
            fi
        else
            echo "DOCKER_HOST: $DOCKER_HOST"
        fi
        echo ""
    fi
}

run(){
	echo "$1"
	eval "$1"
}

get_secret(){
	if [ ! -e ./.secret_key ] && [ -e /dev/random ]; then
		echo "Generating secret in ./.secret_key"
		export WO_SECRET_KEY=$(head -c50 < /dev/random | base64)
		echo $WO_SECRET_KEY > ./.secret_key
	elif [ -e ./.secret_key ]; then
		export WO_SECRET_KEY=$(cat ./.secret_key)
	else
		export WO_SECRET_KEY=""
	fi
}

start(){
	get_secret

	if [[ $dev_mode = true ]]; then
		echo "Starting WebODM in development mode..."
		down
	else
		echo "Starting WebODM..."
	fi
	echo ""
	echo "Using the following environment:"
	echo "================================"
	echo "Host: $WO_HOST"
	echo "Port: $WO_PORT"
 	echo "IPv6: $WO_IPV6"
	echo "Media directory: $WO_MEDIA_DIR"
	echo "Postgres DB directory: $WO_DB_DIR"
	echo "Node directory: $WO_NODE_DIR"
	echo "SSL: $WO_SSL"
	echo "SSL key: $WO_SSL_KEY"
	echo "SSL certificate: $WO_SSL_CERT"
	echo "SSL insecure port redirect: $WO_SSL_INSECURE_PORT_REDIRECT"
	echo "Celery Broker: $WO_BROKER"
	echo "Default Nodes: $WO_DEFAULT_NODES"
	echo "Settings: $WO_SETTINGS"
	echo "Worker memory limit: $WO_WORKER_MEMORY"
	echo "Worker cpus limit: $WO_WORKER_CPUS"
	echo "================================"
	echo "Make sure to issue a $0 down if you decide to change the environment."
	echo ""

	command="$docker_compose -f docker-compose.yml"

    if [[ $WO_DEFAULT_NODES -gt 0 ]]; then
		if [ "${GPU_NVIDIA}" = true ]; then
			command+=" -f docker-compose.nodeodx.gpu.nvidia.yml"
		else
			command+=" -f docker-compose.nodeodx.yml"
		fi

		if [ ! -z "$WO_NODE_DIR" ]; then
			command+=" -f docker-compose.nodeodx.volume.yml"
		fi
    fi

    if [[ $load_micmac_node = true ]]; then
        command+=" -f docker-compose.nodemicmac.yml"
    fi

    if [[ $dev_mode = true ]]; then
        command+=" -f docker-compose.dev.yml"
    fi

	if [ "$WO_SSL" = "YES" ]; then
		if [ -n "$WO_SSL_KEY" ] && [ ! -e "$WO_SSL_KEY" ]; then
			echo -e "\033[91mSSL key file does not exist: $WO_SSL_KEY\033[39m"
			exit 1
		fi
		if [ -n "$WO_SSL_CERT" ] && [ ! -e "$WO_SSL_CERT" ]; then
			echo -e "\033[91mSSL certificate file does not exist: $WO_SSL_CERT\033[39m"
			exit 1
		fi

		command+=" -f docker-compose.ssl.yml"

		method="Lets Encrypt"
		if [ -n "$WO_SSL_KEY" ] && [ -n "$WO_SSL_CERT" ]; then
			method="Manual"
			command+=" -f docker-compose.ssl-manual.yml"
		fi

		if [ "$method" = "Lets Encrypt" ]; then
			# Check port settings
			# as let's encrypt cannot communicate on ports
			# different than 80 or 443
			if [ "$WO_PORT" != "$DEFAULT_PORT" ]; then
				echo -e "\033[93mLets Encrypt cannot run on port: $WO_PORT, switching to 443.\033[39m"
				echo "If you need to use a different port, you'll need to generate the SSL certificate files separately and use the --ssl-key and --ssl-certificate options."
			fi
			export WO_PORT=443
		fi

		# Make sure we have a hostname
		if [ "$WO_HOST" = "localhost" ]; then
			echo -e "\033[91mSSL is enabled, but hostname cannot be set to $WO_HOST. Set the --hostname argument to the domain of your WebODM server (for example: www.mywebodm.org).\033[39m"
			exit 1
		fi

		echo "Will enable SSL ($method)"
	fi

	if [ ! -z "$WO_SETTINGS" ]; then
		if [ ! -e "$WO_SETTINGS" ]; then
			echo -e "\033[91mSettings file does not exist: $WO_SETTINGS\033[39m"
			exit 1
		fi
		command+=" -f docker-compose.settings.yml"
	fi

	if [ ! -z "$WO_WORKER_MEMORY" ]; then
		command+=" -f docker-compose.worker-memory.yml"
	fi

	if [ ! -z "$WO_WORKER_CPUS" ]; then
		command+=" -f docker-compose.worker-cpu.yml"
	fi

 	if [[ $ipv6 = true ]]; then
        command+=" -f docker-compose.ipv6.yml"
	fi

	command="$command up"

	if [[ $detached = true ]]; then
		command+=" -d"
	fi

	run "$command"
}

down(){
	command="$docker_compose -f docker-compose.yml"

	if [ "${GPU_NVIDIA}" = true ]; then
		command+=" -f docker-compose.nodeodx.gpu.nvidia.yml"
	else
		command+=" -f docker-compose.nodeodx.yml"
	fi

	command+=" -f docker-compose.nodemicmac.yml down --remove-orphans"

	run "${command}"
}

rebuild(){
	run "$docker_compose down --remove-orphans"
	run "rm -fr node_modules/ || sudo rm -fr node_modules/"
	run "rm -fr nodeodm/external/NodeODM || sudo rm -fr nodeodm/external/NodeODM"
	run "$docker_compose -f docker-compose.yml -f docker-compose.build.yml build --no-cache"
	#run "docker images --no-trunc -aqf \"dangling=true\" | xargs docker rmi"
	echo -e "\033[1mDone!\033[0m You can now start WebODM by running $0 start"
}

run_tests(){
    # If in a container, we run the actual test commands
    # otherwise we launch this command from the container
    if [[ -f /.dockerenv ]]; then
        test_type=${1:-"all"}
        shift || true
        
        if [[ $test_type = "frontend" || $test_type = "all" ]]; then
            echo -e "\033[1mRunning frontend tests\033[0m"
            run "npm run test $*"
        fi

        if [[ $test_type = "backend" || $test_type = "all" ]]; then
            echo -e "\033[1mRunning backend tests\033[0m"
            run "python manage.py test $*"
        fi

        if [[ $test_type = "all" ]]; then
            echo ""
            echo -e "\033[1mDone!\033[0m Everything looks in order."
        fi
    else
		environment_check
        echo "Running tests in webapp container"
        test_command="/webodm/webodm.sh test $*"
        run "$docker_compose exec webapp /bin/bash -c \"$test_command\""
    fi
}

resetpassword(){
	newpass=$1

	if [[ -n "$newpass" ]]; then
		container_hash=$(docker ps -q --filter "name=webapp")
		if [[ -z "$container_hash" ]]; then
			echo -e "\033[91mCannot find webapp docker container. Is WebODM running?\033[39m"
			exit 1
		fi

		if docker exec "$container_hash" bash -c "echo \"from django.contrib.auth.models import User;from django.contrib.auth.hashers import make_password;u=User.objects.filter(is_superuser=True)[0];u.password=make_password('$newpass');u.save();print('The following user was changed: {}'.format(u.username));\" | python manage.py shell"; then
			echo -e "\033[1mPassword changed!\033[0m"
		else
			echo -e "\033[91mCould not change administrator password. If you need help, please visit https://github.com/WebODM/WebODM/issues/ \033[39m"
		fi
	else
		usage
	fi
}

update(){
	echo "Updating WebODM..."

	hash git 2>/dev/null || git_not_found=true
	if [[ $git_not_found ]]; then
		echo "Skipping source update (git not found)"
	else
		if [[ -d .git ]]; then
			if [[ -d "locale" ]] && [[ -n "$(ls -A locale)" ]]; then
				run "git submodule sync"
			fi
			run "git pull origin master"
		else
			echo "Skipping source update (.git directory not found)"
		fi
	fi

	command="$docker_compose -f docker-compose.yml"

	if [[ $WO_DEFAULT_NODES -gt 0 ]]; then
		if [ "${GPU_NVIDIA}" = true ]; then
			command+=" -f docker-compose.nodeodx.gpu.nvidia.yml"
		else
			command+=" -f docker-compose.nodeodx.yml"
		fi
	fi

	if [[ $load_micmac_node = true ]]; then
		command+=" -f docker-compose.nodemicmac.yml"
	fi

	command+=" pull"
	run "$command"
}

if [[ $1 = "start" ]]; then
	environment_check
	start
elif [[ $1 = "stop" ]]; then
	environment_check
	echo "Stopping WebODM..."

	command="$docker_compose -f docker-compose.yml"

	if [ "${GPU_NVIDIA}" = true ]; then
		command+=" -f docker-compose.nodeodx.gpu.nvidia.yml"
	else
		command+=" -f docker-compose.nodeodx.yml"
	fi
 
	command+=" -f docker-compose.nodemicmac.yml stop"
	run "${command}"
elif [[ $1 = "restart" ]]; then
	environment_check
	echo "Restarting WebODM..."
	down
	start
elif [[ $1 = "down" ]]; then
	environment_check
	echo "Tearing down WebODM..."
	down
elif [[ $1 = "rebuild" ]]; then
	environment_check
	echo  "Rebuilding WebODM..."
	rebuild
elif [[ $1 = "update" ]]; then
	environment_check
	down
	update
	echo -e "\033[1mDone!\033[0m You can now start WebODM by running $0 start"
elif [[ $1 = "liveupdate" ]]; then
	environment_check
	update
	echo -e "\033[1mDone!\033[0m You can now finish the update by running $0 restart"
elif [[ $1 = "checkenv" ]]; then
	environment_check
elif [[ $1 = "test" ]]; then
	shift || true
	run_tests "$@"
elif [[ $1 = "resetadminpassword" ]]; then
	resetpassword "$2"
else
	usage
fi
