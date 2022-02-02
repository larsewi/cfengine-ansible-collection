# Ansible Collection - cfengine.cfengine

This collection integrates CFEngine into Ansible worflows.

## Contents

- [`cfengine` module](./plugins/modules/cfengine.py) -- module (task type) for
  making sure a host is part of the CFEngine-managed infrastructure


## Quickstart

1. Collection installation

   To install this collection, run the following command:

   ```
   ansible-galaxy collection install https://gitlab.com/Northern.tech/CFEngine/cfengine-ansible-collection/uploads/71362febba022da55db9db748d7d399f/cfengine-cfengine-1.0.0.tar.gz
   ```

2. Use the `cfengine` module

   The `cfengine` module can be used in playbooks by adding a task like this:

   ```
   - name: Install and bootstrap CFEngine
     cfengine.cfengine.cfengine:
       policy_server: hub.example.com
       version: 3.18.1
   ```