# Models

## Role in the system

Each JSON file is an identity record for a model available to the local
runtime. It tells the runner which provider and installed model name to call
and which exact digest must be present. It does not download or start a model.

Agent definitions reference these files through `model_profile`; the freeze
manifest records the profile and digest so later runs cannot silently use a
different model behind the same name.

## Add or remove a model

1. Copy an existing profile.
2. Give it a unique `profile_id`.
3. Set the provider, installed model name, and verified 64-character digest.
4. Reference it from one or more agent definitions.
5. Confirm the model is installed and run validation.

To remove one, change all agent references first. Never edit a profile used by
a frozen experiment; create a new profile and experiment ID.
