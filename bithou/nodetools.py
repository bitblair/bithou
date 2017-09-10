import hou
import re

_traversed = dict()
expr_node_pattern = re.compile(r'"([\S\\.]+)"')
file_pattern = re.compile(r'^[\w/\.\-\@\:\?\$\#]*\.\w+$')


class NodeTraverse(object):
    """ Represents a node during a node traversal.
    """
    def __init__(self,
                 node,
                 respect_bypass=True,
                 respect_lock=True,
                 ignore_hda_locked=True,
                 ignore_categories=None):
        """ Represents a node during a node traversal.
        Args:
            node (hou.Node): Node to operate on.
            respect_bypass (bool): Ignore references on nodes that are bypassed.
            respect_lock (bool): Ignore input nodes that are locked.
            ignore_hda_locked (bool): Ignore nodes locked in hdas.
            ignore_categories (list): Ignore categories of nodes.
        """
        self.node = node
        try:
            bypassed = node.isBypassed()
        except AttributeError:
            bypassed = False
        self.inputs = [x for x in node.inputs() if x]
        if respect_lock:
            try:
                self.inputs = [x for x in self.inputs if not x.isHardLocked()]
            except AttributeError:
                pass
        self.outputs = [x for x in node.outputs() if x]
        self.connected = self.inputs + self.outputs

        if bypassed and respect_bypass:
            self.references = []
        else:
            ignore_categories = ignore_categories or []
            if hou.vopNodeTypeCategory() not in ignore_categories:
                ignore_categories.append(hou.vopNodeTypeCategory())
            self.references = self._get_all_references(ignore_hda_locked,
                                                       ignore_categories)

    def _get_all_references(self, ignore_hda_locked, ignore_categories):
        """ Get all references for this node and its children.
        Args:
            ignore_hda_locked (bool): Ignore nodes locked in hdas.
            ignore_categories (list): Ignore categories of nodes.

        Returns:
            list: hou.Node(s) listed as refs.
        """
        refs = set()
        all_children = list(self.node.allSubChildren())
        all_children.append(self.node)
        ignore = set()
        ignore.update(all_children)
        for n in all_children:
            if not is_editable(n) and ignore_hda_locked:
                continue
            elif n.type().category() in ignore_categories:
                continue
            refs.update(self._get_references(n, ignore))
            ignore.update(refs)

        refs = [x for x in refs if x not in self.inputs not in self.outputs]
        return refs

    @staticmethod
    def _get_references(node, ignore=None):
        """ Get references for specified node, and optionally ignore nodes.
        Args:
            node (hou.Node): Node to operate on.
            ignore (list): Nodes to ignore.

        Returns:
            list: hou.Node(s) found as references.
        """
        ignore = ignore or []
        path = node.path()
        global _traversed
        refs = _traversed.get(path, list())
        if not refs:
            refs = find_node_references(node)
            refs = [x for x in refs if x not in ignore]
            _traversed[path] = tuple(refs)
        return refs


def has_expression(parm):
    """ Determines if parm contains an expression.

    Ignores keyframes that use slopes (bezier, easeIn, easeOut, linear, etc).
    Args:
        parm (hou.Parm): Parm to operate on.

    Returns:
        bool: True if parm contains expression, False otherwise.
    """
    keyframes = parm.keyframes()
    if not keyframes:
        return False
    else:
        for keyframe in keyframes:
            try:
                uses_slope = keyframe.isSlopeUsed()
            except AttributeError:
                uses_slope = False
            if not uses_slope:
                return True
    return False


def find_parm_references(parm):
    """ Find node references on specified parm.
    Args:
        parm (hou.Parm): Parm to operate on.

    Returns:
        list: hou.Node(s) this references.
    """
    ref_parm = parm.getReferencedParm()
    if ref_parm != parm:
        return [ref_parm.node()]
    expr = None
    node = parm.node()
    if has_expression(parm):
        expr = parm.expression()
    elif parm.parmTemplate().dataType().name() == 'String':
        expr = parm.unexpandedString()
        val = parm.eval()
        if expr == val:
            ref_node = node.node(val)
            if ref_node:
                return [ref_node]
            else:
                ref_parm = node.parm(val)
                if ref_parm:
                    return [ref_parm.node()]
    refs = []
    if expr:
        for ref in expr_node_pattern.findall(expr):
            ref_node = node.node(ref)
            if ref_node:
                refs.append(ref_node)
            else:
                ref_parm = node.parm(ref)
                if ref_parm:
                    refs.append(ref_parm.node())

    return refs


def find_node_references(node):
    """ Find nodes this node references.
    Args:
        node (hou.Node): Node to operate on.

    Returns:
        list: hou.Node(s) this node references.
    """
    all_refs = set()
    for p in node.parms():
        all_refs.update(find_parm_references(p))
    return list(all_refs)


def is_editable(node):
    """ Determine if node is editable.
    Args:
        node (hou.Node): Node to operate on.

    Returns:
        bool: True if editable, False otherwise.
    """
    if node.isInsideLockedHDA():
        return node.isEditableInsideLockedHDA()
    return True


def get_parents(node, root=hou.node('/obj')):
    """ Find all parents of node until root is met.
    Args:
        node (hou.Node): Node to start from.
        root (hou.Node): Node to stop at.
    """
    parents = list()
    while node != root:
        node = node.parent()
        parents.append(node)
    return parents


def traverse(root,
             respect_bypass=True,
             respect_lock=True,
             ignore_hda_locked=True,
             ignore_categories=None,
             include_root=True):
    """ Traverse a graph, returning an iterator of traversed nodes.
    Args:
        root (hou.Node): Root to start traversal from.
        respect_bypass (bool): Ignore references on nodes that are bypassed.
        respect_lock (bool): Ignore input nodes that are locked.
        ignore_hda_locked (bool): Ignore nodes locked in hdas.
        ignore_categories (list): Ignore categories of nodes.
        include_root (bool): Include the root in the traversal.
    Yields:
        tuple: hou.Node(s) traversed at point in graph.
    """
    global _traversed
    _traversed.clear()
    roots = [root]
    skip_root = not include_root
    while roots:
        if skip_root:
            traversed = [NodeTraverse(r,
                                      respect_bypass=respect_bypass,
                                      respect_lock=respect_lock,
                                      ignore_hda_locked=ignore_hda_locked,
                                      ignore_categories=ignore_categories)
                         for r in roots]
            roots = set()
            for t in traversed:
                _all = t.inputs + t.references
                _all = [n for n in _all if n.path() not in _traversed.keys()]
                roots.update(_all)
        skip_root = True
        yield tuple(roots)


def is_valid_file(value):
    """ Determines if passed value points to a valid file.
    Args:
        value (str): Value to test.

    Returns:
        bool: True if valid file, False otherwise.
    """
    if not value:
        return False
    return bool(file_pattern.match(value))


def find_file_references(node, inspect_hda=True, skip_vops=True):
    """ Find file references for specified node.
    Args:
        node (hou.Node): Node to operate on.
        inspect_hda (bool): Inspect child nodes of hdas.
        skip_vops (bool): Skip vop nodes, improving performance.

    Returns:
        tuple: List of file references found.
    """
    refs = set()
    if inspect_hda and not node.isEditable():
        nodes = [node]
        nodes.extend(node.allSubChildren())
    else:
        nodes = [node]
    if skip_vops:
        nodes = [n for n in nodes if
                 n.type().category() != hou.vopNodeTypeCategory()]
    for inode in nodes:
        for parm in inode.parms():
            if not parm.parmTemplate().dataType() == hou.parmData.String:
                continue
            elif parm.isDisabled():
                continue
            elif parm.getReferencedParm().node in nodes:
                continue
            val = parm.eval()
            if val in refs:
                continue
            elif inode.node(val):
                continue
            elif is_valid_file(val):
                refs.add(val)

    return tuple(refs)
