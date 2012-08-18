# vim: tabstop=4 shiftwidth=4 softtabstop=4

import logging
import os
import shlex
import subprocess

LOG = logging.getLogger(__name__)


def execute(cmd, root_helper=None, process_input=None, addl_env=None,
            check_exit_code=True, return_stderr=False):
    if root_helper:
        cmd = shlex.split(root_helper) + cmd
    cmd = map(str, cmd)

    LOG.debug("Running command: " + " ".join(cmd))
    env = os.environ.copy()
    if addl_env:
        env.update(addl_env)
    obj = subprocess.Popen(cmd, shell=False, stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=env)

    _stdout, _stderr = (process_input and
                        obj.communicate(process_input) or
                        obj.communicate())
    obj.stdin.close()
 
    LOG.debug("Return: %s" % obj.returncode)
    LOG.debug("Stdout: %r" % _stdout) 
    LOG.debug("Stderr: %r" % _stderr)
    
    if obj.returncode and check_exit_code:
        m = ("\nCommand: %s\nExit code: %s\nStdout: %r\nStderr: %r"
             % (cmd, obj.returncode, _stdout, _stderr))
        raise RuntimeError(m)

    return return_stderr and (_stdout, _stderr) or _stdout
