#!/bin/bash

SYSTEMD_UNIT_ENABLE="${SYSTEMD_UNIT_ENABLE:-true}"

make executable-linux-docker
sudo mv large-model-proxy-linux /usr/local/bin/large-model-proxy
sudo chmod +x /usr/local/bin/large-model-proxy
sudo cp monitor/large-model-proxy-monitor.py /usr/local/bin/large-model-proxy-monitor

if [[ ! -f /etc/large-model-proxy/config.jsonc ]]; then
  sudo cp monitor/config.example.jsonc /etc/large-model-proxy/config.jsonc
fi

if [[ -d /etc/systemd/system/ ]]; then
  sudo cp monitor/large-model-proxy-monitor.service /etc/systemd/system/large-model-proxy-monitor.service
  sudo systemctl daemon-reload
  if $SYSTEMD_UNIT_ENABLE; then
    sudo systemctl enable large-model-proxy-monitor.service
    sudo systemctl start large-model-proxy-monitor.service
  fi
fi
