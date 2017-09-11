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
        self.traversed = dict()
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
        self.ignore_hda_locked = ignore_hda_locked

        ignore_categories = ignore_categories or []
        if hou.vopNodeTypeCategory() not in ignore_categories:
            ignore_categories.append(hou.vopNodeTypeCategory())
        self.ignore_categories = ignore_categories

        if bypassed and respect_bypass:
            self.references = []
        else:
            self.references = self._get_references()

        self.child_output = []
        if not self.node.isLockedHDA():
            self.child_output = list(get_child_output(node))

        self.to_traverse = self.references + self.inputs + self.child_output

    def _get_references(self):
        """ Get references for specified node, and optionally ignore nodes.
        Returns:
            list: hou.Node(s) found as references.
        """
        path = self.node.path()
        global _traversed
        refs = _traversed.get(path, list())
        if not refs:
            refs = [n for n in find_node_references(self.node)
                    if not n == self.node]
            self.traversed[path] = tuple(refs)
        return list(refs)


def get_output_nodes(node, only_connected=True):
    """ Find any output nodes inside this node. This only works on SOPs.
    Args:
        node (hou.Node): Node to operate on.
        only_connected (bool): Only return outputs that have active connections.

    Returns:
        tuple: Output nodes inside this node.
    """
    if not node.childTypeCategory() == hou.sopNodeTypeCategory():
        return ()
    outputs = list()
    connections = node.outputConnections()
    indices = [c.inputItemOutputIndex() for c in connections]
    for n in node.children():
        if n.type().name() == 'output':
            output_index = n.evalParm('outputidx')
            if only_connected and not output_index in indices:
                continue
            outputs.append(n)
    return tuple(outputs)


def get_child_output(node, only_connected=True):
    """ Find the output/display/render node for this node.
    Args:
        node (hou.Node): Node to operate on.
        only_connected (bool): If outputs are found, only return connected nodes.

    Returns:
        tuple: Output node(s), this can be multiple if multiple output nodes
        exist.
    """
    outputs = get_output_nodes(node, only_connected=only_connected)
    if outputs:
        return outputs
    category = node.childTypeCategory()
    if category == hou.sopNodeTypeCategory():
        return node.renderNode(),
    elif category == hou.dopNodeTypeCategory():
        return node.displayNode(),
    else:
        return ()


def has_expression(parm):
    """ Determines if parm contains an expression.

    Ignores keyframes that use slopes (bezier, easeIn, easeOut, linear, etc).
    Args:
        parm (hou.Parm): Parm to operate on.

    Returns:
        bool: True if parm contains expression, False otherwise.
    """
    keyframes = parm.keyframes()
    if len(keyframes) != 1:
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
                         for r in roots if not r.type().isManager()]
            roots = set()
            for t in traversed:
                to_traverse = t.to_traverse
                to_traverse = [n for n in to_traverse
                               if n.path() not in _traversed.keys()]
                _traversed.update(t.traversed)
                roots.update(to_traverse)
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


def find_file_references(node, inspect_hda=False, skip_vops=True):
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
        inode.updateParmStates()
        for parm in inode.parms():
            if not parm.parmTemplate().dataType() == hou.parmData.String:
                continue
            elif not parm.eval():
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
