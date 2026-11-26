"""The passports of the boxes in ``primer-ops`` (DM-158; TZ 0.7.41 O).

The Panel is a UI over the ops repository: it reads a server's passport with
its own age key, writes an edit as one commit of its own, and "apply" is the
command ``update`` of the queue (PRIMER-PANEL-TZ-2 1.1 §1 p.4). It keeps no
copy of a passport and never gives a secret's value back.

- ``run`` -- the one boundary of subprocess: ``git`` and ``sops``;
- ``connect`` -- ssh's way out through the machine's proxy;
- ``repo`` -- the ops repository: fetch, a file at a commit, a commit, a push;
- ``passport`` -- decrypting, the view without secrets, an edit by ``sops``;
- ``router`` -- the routes of a server's passport.
"""
