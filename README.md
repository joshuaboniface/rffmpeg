# rffmpeg

rffmpeg is a remote FFmpeg wrapper used to execute FFmpeg commands on a remote server via SSH. It is most useful in situations involving media servers such as Jellyfin (our reference user), where one might want to perform transcoding actions with FFmpeg on a remote machine or set of machines to better handle the load.

## Usage

1. Install the required Python 3 dependencies: `yaml` and `subprocess`.

1. Create the directory `/etc/rffmpeg`.

1. Copy the `rffmpeg.yml.sample` file to `/etc/rffmpeg/rffmpeg.yml` and edit it to suit your needs.

1. Install `rffmpeg.py` somewhere useful, for instance at `/usr/local/bin/rffmpeg.py`.

1. Create symlinks for the command names `ffmpeg` and `ffprobe` to `rffmpeg.py`, for instance `/usr/local/bin/ffmpeg -> /usr/local/bin/rffmpeg.py` and `/usr/local/bin/ffprobe -> /usr/local/bin/rffmpeg.py`.

1. Edit your media program to use the `rffmpeg.py` binary (via the symlink names) instead of the standard `ffmpeg` binary.

1. Profit!

## rffmpeg options

### Remote hosts

rffmpeg supports setting multiple hosts. It keeps state in `/run/shm/rffmpeg`, of all running processes. These state files are used during rffmpeg's initialization in order to determine the optimal target host. rffmpeg will run through these hosts sequentially, choosing the one with the fewest running rffmpeg jobs. This helps distribute the transcoding load across multiple servers.

## Full setup guide

This example setup is the one I use for `rffmpeg`, involving a media server (`jf1`) and a remote transcode server (`gpu1`). Both systems run Debian GNU/Linux, though the commands below should also work on Ubuntu.

1. Prepare the media server (`jf1`) with Jellyfin. Make note of the "Transcode path" in the Playback settings menu (e.g. `/var/lib/jellyfin/transcoding-temp`).

1. On the media server, create an SSH keypair owned by the Jellyfin service user; save this SSH key somewhere readable to the service user: `sudo -u jellyfin mkdir -p /var/lib/jellyfin/.ssh && sudo -u jellyfin ssh-keygen -t rsa -f /var/lib/jellyfin/.ssh/id_rsa`

1. Install the rffmpeg program as detailed in the above section, including creating the `/etc/rffmpeg/rffmpeg.yml` configuration file and symlinks.

1. Install the NFS kernel server: `sudo apt -y install nfs-kernel-server`

1. Export the "Transcode path" directory found in step 1 with NFS; you will need to know the local IP address of the transcode server(s) (e.g. `10.0.0.100`) to lock this down; alternatively, use your entire local network range (e.g. `10.0.0.0/24`): `echo '/var/lib/jellyfin/transcoding-temp 10.0.0.100/32(rw,sync,no_subtree_check)' | sudo tee -a /etc/exports && sudo systemctl restart nfs-kernel-server`

1. On the transcode server, install any required tools or programs to make use of hardware transcoding; this is optional if you only use software (i.e. CPU) transcoding.

1. Install the `jellyfin-ffmpeg` package to provide an FFmpeg binary; follow the Jellyfin installation instructions for details on setting up the Jellyfin repository, though install only `jellyfin-ffmpeg`.

1. Install the NFS client utilities: `sudo apt install -y nfs-common`

1. Create a user for rffmpeg to SSH into the server as. This user should match the `jellyfin` user on the media server in every way, including UID (`id jellyfin` on the media server), home path, and groups.

1. Install the SSH public key created in step 2 into the new user's home directory: `sudo -u jellyfin mkdir -p /var/lib/jellyfin/.ssh && echo 'ssh-rsa MyJellyfinUserPublicKey' | sudo -u jellyfin tee /var/lib/jellyfin/.ssh/authorized_keys`

1. Ensure that the "Transcode path" directory exists at the same location as on the media server; create it if required: `sudo mkdir -p /var/lib/jellyfin/transcoding-temp`

1. Mount the media server NFS transcode share at the transcode directory: `echo 'jf1:/var/lib/jellyfin/transcoding-temp /var/lib/jellyfin/transcoding-temp nfs defaults,vers=3,sync 0 0' | sudo tee -a /etc/fstab && sudo mount -a`

1. Mount your media directory on the transcode server at the same location as on the media server and using the same method; if your media is local to the media server, export it with NFS similarly to the transcode directory.

1. On the media server, attempt to SSH to the transcode server as the `jellyfin` user using the key from step 2; this both tests the connection as well as saves the transcode server SSH host key locally: `sudo -u jellyfin ssh -i /var/lib/jellyfin/.ssh/id_rsa jellyfin@gpu1`

1. Verify that rffmpeg itself works by calling its `ffmpeg` alias with the `-version` option: `sudo -u jellyfin /usr/local/bin/ffmpeg -version`

1. In Jellyfin, set the rffmpeg binary, via its `ffmpeg` symlink, as your "FFmpeg path" in the Playback settings; optionally, enable any hardware encoding you configured in step 6.

1. Try running a transcode and verifying that the `rffmpeg` program works as expected. The flow should be:

    1. Jellyfin calls rffmpeg with the expected arguments.

    1. FFmpeg begins running on the transcode server.

    1. The FFmpeg process writes the output files to the NFS-mounted temporary transcoding directory.

    1. Jellyfin reads the output files from the NFS-exported temporary transcoding directory and plays back normally.
