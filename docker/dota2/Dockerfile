# Taken & Updated from https://github.com/TimZaman/dotaservice/blob/master/docker/Dockerfile-dota
FROM ubuntu:20.04

# Make sure to install steam and Dota first, as those docker layers will be biggest.
# Install, update & upgrade packages
# Create user for the server
# This also creates the home directory we later need
# Clean TMP, apt-get cache and other stuff to make the image smaller
RUN apt-get -q update \
 && apt-get install -y \
    lib32stdc++6 \
    lib32gcc1 \
    curl && \
    apt-get -y upgrade && \
    apt-get clean autoclean && \
    apt-get autoremove -y && \
    rm -rf /var/lib/{apt,dpkg,cache,log}/

# Create Directory for SteamCMD
# Download SteamCMD
# Extract and delete archive
RUN mkdir -p /root/steamcmd \
 && cd /root/steamcmd \
 && curl -o steamcmd_linux.tar.gz "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz" \
 && tar zxf steamcmd_linux.tar.gz \
 && rm steamcmd_linux.tar.gz

ARG user
ARG pwd
ARG guard
RUN /root/steamcmd/steamcmd.sh +login ${user} ${pwd} ${guard} +app_update 570 +quit

RUN ln -s ~/steamcmd/linux64 ~/.steam/sdk64
