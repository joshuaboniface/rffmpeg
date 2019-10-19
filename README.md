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

## Full setup

This example setup is the one I use for `rffmpeg`, involving a Jellyfin server (`jf1`) and a remote transcode server (`gpu1`).

1. Prepare the remote transcode server. This involves the following steps:

   1. Install any required tools or programs to make use of hardware transcoding. This is optional if you only plan to use software (i.e. CPU) transcoding.

   1. Create a temporary transcoding directory somewhere on the system. Ideally, this should be fast scratch storage with no persistence required. In my case I use a pair of RAID-0 SSDs, though you could use a ramdisk if you have sufficient RAM. For my purposes, I put this directory at `/var/transcode` and mount my SSD RAID there.

   1. Create a user to accept SSH connections in and run the FFmpeg commands. I use a user called `jellyfin` with a home directory of `/var/lib/jellyfin`, identical to the user that is created by the Jellyfin server itself - this is important for the directory layout to work.

   1. Ensure the temporary transcoding directory is owned by the new user.

   1. Create a symlink from the user's home directory to the temporary transcoding directory. This much match the Jellyfin file layout to preserve paths. For insance, if your `transcoding-temp` directory on the Jellyfin server is at `/var/lib/jellyfin/transcoding-temp`, the symlink must exist at the same location on the transcode server.

   1. Similarly to the transcoding directory, ensure your media volume is mounted on the transcode server at the same location as on the Jellyfin server.

   1. Install an FFmpeg binary, in my case the `jellyfin-ffmpeg` package, on the transcode server.

   1. Install the NFS kernel server, and set up an export of your temporary transcoding directory such that the Jellyfin server can mount it.

1. On your Jellyfin server, create a new SSH private keypair owned by the Jellyfin service user.

1. Install the public key of the new SSH private keypair under the remote user on the transcode server.

1. Verify that SSH is successful from the Jellyfin server (as the Jellyfin user) to the transcode server as expected. Running `sudo -u <jellyfin-user> rffmpeg.py` once with no arguments will accomplish this test. This also ensures that the SSH host key of the remote server is saved before Jellyfin attempts to run the command.

1. Install the NFS client, and mount the temporary transcoding directory from the remote server to your `transcoding-temp` directory as set in Jellyfin.

1. Install the `rffmpeg` program as detailed above.

1. In Jellyfin, set the `rffmpeg.py` binary, via its `ffmpeg` symlink, as your "FFmpeg path". The symlinks are important for Jellyfin to properly call the `ffprobe` command as well.

1. Try running a transcode and verifying that the `rffmpeg` program works as expected. The flow should be:

    1. Jelyfin calls `rffmpeg.py` with the expected arguments.

    1. FFmpeg begins running on the transcode server; the file paths should all be valid there as they would be on the Jellyfin machine.

    1. The FFmpeg process writes the output files to the NFS-exported temporary transcoding directory.

    1. Jelyfin reads the output files from the NFS-mounted temporary transcoding directory and plays back normally.
