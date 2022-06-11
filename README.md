# rffmpeg

rffmpeg is a remote FFmpeg wrapper used to execute FFmpeg commands on a remote server via SSH. It is most useful in situations involving media servers such as Jellyfin (our reference user), where one might want to perform transcoding actions with FFmpeg on a remote machine or set of machines to better handle the load.

## Quick usage

1. Install the required Python 3 dependencies `yaml` and `subprocess` (`sudo apt install python3-yaml python3-subprocess` in Debian).

1. Create the directory `/etc/rffmpeg`.

1. Copy the `rffmpeg.yml.sample` file to `/etc/rffmpeg/rffmpeg.yml` and edit it to suit your needs.

1. Install `rffmpeg.py` somewhere useful, for instance at `/usr/local/bin/rffmpeg.py`.

1. Create symlinks for the command names `ffmpeg` and `ffprobe` to `rffmpeg.py`, for example `sudo ln -s /usr/local/bin/rffmpeg.py /usr/local/bin/ffmpeg` and `sudo ln -s /usr/local/bin/rffmpeg.py /usr/local/bin/ffprobe`.

1. Set your media program to use `rffmpeg.py` via the symlink names created above, instead of any other `ffmpeg` binary.

1. Profit!

For a more detailed setup guide, see the section "Full setup guide" below.

## rffmpeg options and caveats

The `rffmpeg.yml.sample` is self-documented for the most part. Some additional important information you might need is presented below.

### Remote hosts

rffmpeg supports setting multiple hosts. It keeps state in `/run/shm/rffmpeg` of all running processes, and these state files are used during rffmpeg's initialization in order to determine the optimal target host. rffmpeg will run through these hosts sequentially, choosing the one with the fewest running rffmpeg jobs. This helps distribute the transcoding load across multiple servers, and can also provide redundancy if one of the servers is offline - rffmpeg will detect if a host is unreachable and set it "bad" for the remainder of the run, thus skipping it until the process completes.

Hosts can also be assigned weights (see `rffmpeg.yml.sample` for an example) that allow the host to take on that many times the number of active processes versus weight-1 hosts. The `rffmpeg` process does a floor division of the number of active processes on a host with that host weight to determine its "weighted [process] count", which is then used instead to determine the lease-loaded host to use.

Note that `rffmpeg` does not take into account actual system load, etc. when determining which host to use; it treats each running command equally regardless of how intensive it actually is.

### Localhost and fallback

If one of the hosts in the config file is called "localhost", rffmpeg will run locally without SSH. This can be useful if the local machine is also a powerful transcoding device.

In addition, rffmpeg will fall back to "localhost" should it be unable to find any working remote hosts. This helps prevent situations where rffmpeg cannot be run due to none of the remote host(s) being available.

In both cases, note that, if hardware acceleraton is configured, it *must* be available on the local host as well, or the `ffmpeg` commands will fail. There is no easy way around this without rewriting flags, and this is currently out-of-scope for `rffmpeg`. You should always use a lowest-common-denominator approach when deciding on what additional option(s) to enable, such that any configured host can run any process.

The exact path to the local `ffmpeg` and `ffprobe` binaries can be overridden in the configuration, should their paths not match those of the remote system(s). If these options are not specified, the remote paths are used.

### Terminating rffmpeg

When running rffmpeg manually, *do not* exit it with `Ctrl+C`. Doing so will likely leave the `ffmpeg` process running on the remote machine. Instead, enter `q` and a newline ("Enter") into the rffmpeg process, and this will terminate the entire command cleanly. This is the method that Jellyfin uses to communicate the termination of an `ffmpeg` process.
`G
## Full setup guide

This example setup is the one I use for `rffmpeg` with Jellyfin, involving a media server (`jf1`) and a remote transcode server (`gpu1`). Both systems run Debian GNU/Linux, though the commands below should also work on Ubuntu. Note that Docker is not officially supported with `rffmpeg` due to the complexity of exporting Docker volumes with NFS, the path differences, and the fact that I don't use Docker, but if you do figure it out a PR is welcome.

1. Prepare the media server (`jf1`) with Jellyfin using the standard `.deb` install. Make note of the main Jellyfin data path, usually `/var/lib/jellyfin` unless you change it. Note that if you change this path, or put the various subdirectories such as the `transcodes` or `data/subtitles` directories elsewhere, you may need to alter the NFS steps below to accommodate this.

1. On the media server, create an SSH keypair owned by the Jellyfin service user; save this SSH key somewhere readable to the service user: `sudo -u jellyfin mkdir -p -m 0700 /var/lib/jellyfin/.ssh && sudo -u jellyfin ssh-keygen -t rsa -f /var/lib/jellyfin/.ssh/id_rsa`.

1. Copy (or symlink) the new SSH public key created in the previous step to `authorized_keys`; this will be used later when the Jellyfin data directory is mounted on the transcode server: `sudo -u jellyfin cp -a /var/lib/jellyfin/.ssh/id_rsa.pub /var/lib/jellyfin/.ssh/authorized_keys`

1. Install the rffmpeg program as detailed in the "Quick usage" section above, including creating the `/etc/rffmpeg/rffmpeg.yml` configuration file and symlinks.

1. Install the NFS kernel server: `sudo apt -y install nfs-kernel-server`

1. Export your Jellyfin data path found in step 1 with NFS; you will need to know the local IP address of the transcode server(s) (e.g. `10.0.0.100`) to lock this down; alternatively, use your entire local network range (e.g. `10.0.0.0/24`), though this is not recommended for security reasons: `echo '/var/lib/jellyfin 10.0.0.100/32(rw,sync,no_subtree_check)' | sudo tee -a /etc/exports && sudo systemctl restart nfs-kernel-server`

1. On the transcode server, install any required tools or programs to make use of hardware transcoding; this is optional if you only use software (i.e. CPU) transcoding.

1. Install the `jellyfin-ffmpeg` package to provide an FFmpeg binary; follow the Jellyfin installation instructions for details on setting up the Jellyfin repository, though install only `jellyfin-ffmpeg`. While you can technically install any `ffmpeg` binary you wish, we recommend using Jellyfin's official `ffmpeg` for Jellyfin users to maximize compatibility.

1. Install the NFS client utilities: `sudo apt install -y nfs-common`

1. Create a user for rffmpeg to SSH into the server as. This user should match the `jellyfin` user on the media server in every way, including UID (`id jellyfin` on the media server), home path, and groups.

1. Ensure that the Jellyfin data directory exists at the same location as on the media server; create it if required, and set it immutable to prevent unintended writes: `sudo mkdir -p /var/lib/jellyfin && sudo chattr +i /var/lib/jellyfin`

1. Mount the media server NFS data share at the same directory on the transcode server: `echo 'jf1:/var/lib/jellyfin /var/lib/jellyfin nfs defaults,vers=3,sync 0 0' | sudo tee -a /etc/fstab && sudo mount -a`

1. Mount your media directory on the transcode server at the same location as on the media server and using the same method; if your media is local to the media server, export it with NFS in addition to the data directory.

1. On the media server, attempt to SSH to the transcode server as the `jellyfin` user using the key from step 2; this both tests the connection as well as saves the transcode server SSH host key locally: `sudo -u jellyfin ssh -i /var/lib/jellyfin/.ssh/id_rsa jellyfin@gpu1`

1. Repeat the above step for any additional host(s), if applicable.

1. Verify that rffmpeg itself works by calling its `ffmpeg` alias as the service user with the `-version` option: `sudo -u jellyfin /usr/local/bin/ffmpeg -version`

1. In Jellyfin, set the rffmpeg binary, via its `ffmpeg` symlink, as your "FFmpeg path" in the Playback settings; optionally, enable any hardware encoding you configured in step 7.

1. Try running a transcode and verifying that the `rffmpeg` program works as expected by checking the log file specified in the `rffmpeg.yml` configuration. The flow should be:

    1. Jellyfin calls rffmpeg with the expected arguments.

    1. FFmpeg begins running on the transcode server.

    1. The FFmpeg process writes the output files to the NFS-mounted temporary transcoding directory.

    1. Jellyfin reads the output files from the NFS-exported temporary transcoding directory and plays back normally.

1. `rffmpeg` will also be used during other tasks in Jellyfin that require `ffmpeg`, for instance image extraction during library scans and subtitle extraction.

### NOTE for NVEnv/NVDec HWA

If you are using NVEnv/NVDec, it's probably a good idea to symlink the `.nv` folder inside the Jellyfin user's homedir (i.e. `/var/lib/jellyfin/.nv`) to somewhere outside of the NFS volume on both sides. For example:

    jf1  $ sudo mv /var/lib/jellyfin/.nv /var/lib/nvidia-cache
    jf1  $ sudo ln -s /var/lib/nvidia-cache /var/lib/jellyfin/.nv
    gpu1 $ sudo mkdir /var/lib/nvidia-cache
    gpu1 $ sudo chown jellyfin /var/lib/nvidia-cache
    gpu1 $ ls -alh /var/lib/jellyfin
    [...]
    lrwxrwxrwx  1 root     root         17 Jun 11 15:51 .nv -> /var/lib/nvidia-cache
    [...]

Be sure to adjust these paths to match your Jellyfin setup. The name of the target doesn't matter too much, as long as `.nv` inside the homedir is symlinked to it and it is owned by the `jellyfin` service user.

This is because some functions of FFMpeg's NVEnc/NVDec stack - specifically the `scale_cuda` and `tonemap_cuda` filters - leverage this directory to cache their JIT codes, and this can result in very slow startup times for FFMpeg on the remote side due to NFS locking issues. See https://developer.nvidia.com/blog/cuda-pro-tip-understand-fat-binaries-jit-caching/ for further information.

Alternatively, you can simplify the NFS mount to only export and mount the directories that are actually required to pass transcoded data back (at the least, `transcodes` and `data/subtitles`) over NFS, and leave the rest of the directory local to the remote host, but this likely isn't required with this workaround and makes setup more complex. Based on that link, you might also be able to experiment with the environment variables that control the JIT caching. Feel free to experiment and find the best solution for your setup.
