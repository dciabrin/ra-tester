'''Resource Agent Config

A Resource Agent config defines  the config
Meanenvironment with namespace
 '''

__copyright__ = '''
Copyright (C) 2015-2018 Damien Ciabrini <dciabrin@redhat.com>
Licensed under the GNU GPL.
'''


def RAConfig(env, setting_prefix, settings):
    config = {}
    for k, v in settings.items():
        fullk = setting_prefix+":"+k
        if env.has_key(fullk):
            config[k] = env[fullk]
        elif env.has_key(k):
            config[k] = env[k]
        else:
            config[k] = v
    return config
