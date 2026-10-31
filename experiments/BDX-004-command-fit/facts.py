"""Read fixture observations without treating an unobserved value as absent."""
import re


def observation(profile, category, name):
    return profile['document']['categories'].get(category, {}).get('observations', {}).get(name, {})


def value(profile, category, name):
    obs = observation(profile, category, name)
    return obs.get('value') if obs.get('status') == 'observed' else None


def version(text):
    nums = re.match(r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?', str(text))
    return tuple(int(v or 0) for v in nums.groups()) if nums else None


def python_facts(profile, program, text):
    if program == 'py':
        requested = re.search(r'\bpy -(\d+\.\d+)\b', text)
        versions = value(profile, 'software.python', 'py_launcher_versions')
        if requested and versions is not None and requested[1] not in versions:
            return {'version_mismatch': True}
        assumed = profile.get('assumptions', {}).get('launcher_python')
        return assumed or {}
    interpreters = value(profile, 'software.python', 'interpreters') or []
    return next((i for i in interpreters if i.get('found_via') == program + ' on PATH'), {})


def program(profile, requirements, name, installed):
    """(on PATH / not found on PATH / unknown, version); scoped to the fixture."""
    if name in installed:
        return True, installed[name]
    if name in requirements.get('missing_programs', []):
        return False, None
    if name.lower() in {p.lower() for p in requirements.get('assumed_programs', [])}:
        return True, None
    if name in ('python', 'python3') or re.fullmatch(r'python3\.\d+', name):
        facts = python_facts(profile, name, name)
        if facts.get('version'):
            return True, facts['version']
        obs = observation(profile, 'software.python', 'interpreters')
        if obs.get('status') == 'observed' and all('version' in i for i in obs['value']):
            return False, None
        return (False, None) if obs.get('reason') == 'not_found_on_path' else (None, None)
    mapping = {'py': ('software.python', 'py_launcher_versions'),
               'nvidia-smi': ('software.gpu_stack', 'cuda_driver'),
               'docker': ('development.containers', 'docker_client'),
               'podman': ('development.containers', 'podman_client')}
    search = [mapping[name]] if name in mapping else [
        ('software.tools', name), ('software.package_managers', name),
        ('software.runtimes', name), ('system.shell', name)]
    for category, field in search:
        obs = observation(profile, category, field)
        if obs.get('status') == 'observed':
            return True, obs['value'] if isinstance(obs['value'], str) else None
        if obs.get('reason') in ('not_found_on_path', 'not_found'):
            return False, None
    return None, None
