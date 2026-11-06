FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm
# The base image's Yarn apt repo has no valid GPG key, which makes apt-get update fail
# when the docker-outside-of-docker feature is installed. We do not use Yarn.
RUN rm -f /etc/apt/sources.list.d/yarn.list
