Tool to port maps to cs1.


## Known Limitations

There are some known limitations:

* The script cannot port minimaps correctly.
* In case the script cannot find an exact match for a shader it chooses a
  similar shader which might or might not have similar visual appearance.
* The collision of the new map might be broken (works for some people and
  doesn't for others).
* The script doesn't handle .ops files and the associated objects references
  in these .ops files. Resulting maps might be missing objects.

We expect to fix these over time.
