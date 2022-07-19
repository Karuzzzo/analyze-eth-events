# Installation




## OS
Ubuntu 20.04

## Install Python packages


Install python3.9 on system, if you don't have one 
```
sudo apt-get install software-properties-common

sudo add-apt-repository ppa:deadsnakes/ppa

sudo apt-get install python3.9

sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.9 2

```

```
python3 -V # must return 3.9.+
```

Install cython and other tools, needed by poetry and web3-flashbots
```
sudo apt install libpython3.9-dev
```

Install poetry
```
# docs at: https://python-poetry.org/docs/
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python3 -
```

## Clone repo
```
git clone git@github.com:Karuzzzo/analyze-eth-events.git
cd analyze-eth-events
```

Install all dependencies and environment by poetry
```
poetry install
```

## Create ```.env``` file
This file stores bot private key, flashbots user private key, credentials for Postgres SQLdatabase, URI for Ethereum node, Flashbots relay endpoint, and many other SENSITIVE information.
File contents should look like file ```env.example``` in repo

### WARNING! file ```.env``` contains private keys and API keys, be careful

## Run project 

Run txpoolmon.py
```
# For help use --help parameter
poetry run python3 parse-new-events.py
```
