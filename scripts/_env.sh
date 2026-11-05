# Sourced by setup.sh and seed.sh (not run directly).
# Loads .env without overriding variables that are already set: the dev container
# sets the URLs with service names (postgres, mongo) instead of 127.0.0.1; those win.
if [[ -f .env ]]; then
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    [[ -z "${!key+x}" ]] && export "$key=$value"
  done < .env
fi
