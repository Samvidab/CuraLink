#!/usr/bin/env bash
# One-time hardening + Docker setup for a fresh Vultr Ubuntu 24.04 instance. Run as root:
#   ssh root@SERVER_IP 'bash -s' < deploy/vultr/provision.sh
# Creates user `deploy` (your SSH key, sudo), disables root and password SSH logins, firewall: 22/80/443 only.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get -y -o Dpkg::Options::=--force-confold upgrade
apt-get install -y docker.io docker-compose-v2 ufw fail2ban unattended-upgrades rsync sqlite3
systemctl enable --now docker
dpkg-reconfigure -f noninteractive unattended-upgrades

id deploy >/dev/null 2>&1 || adduser --disabled-password --gecos "" deploy
usermod -aG sudo,docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
install -m 600 -o deploy -g deploy /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
echo "deploy ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-deploy && chmod 440 /etc/sudoers.d/90-deploy

cat > /etc/ssh/sshd_config.d/90-curalink.conf <<'CONF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
CONF
systemctl reload ssh || systemctl reload sshd

ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable
systemctl enable --now fail2ban

install -d -m 750 /opt/curalink /opt/curalink/app
install -d -m 700 -o 10001 -g 10001 /opt/curalink/data /opt/curalink/data/secrets /opt/curalink/data/backups
chown deploy:deploy /opt/curalink/app
# Nightly SQLite backup on the server (keeps 14 days).
cat > /etc/cron.d/curalink-backup <<'CRON'
15 3 * * * root sqlite3 /opt/curalink/data/curalink.db ".backup /opt/curalink/data/backups/curalink-$(date +\%F).db" && find /opt/curalink/data/backups -name 'curalink-*.db' -mtime +14 -delete
CRON
echo "Provisioned. Log in as: ssh deploy@$(hostname -I | awk '{print $1}')"
