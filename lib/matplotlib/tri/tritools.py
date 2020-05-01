"""
Tools for triangular grids.
"""

import numpy as np

from matplotlib import cbook
from matplotlib.tri import Triangulation


class TriAnalyzer:
    """
    Define basic tools for triangular mesh analysis and improvement.

    A TriAnalyzer encapsulates a `.Triangulation` object and provides basic
    tools for mesh analysis and mesh improvement.

    Attributes
    ----------
    scale_factors

    Parameters
    ----------
    triangulation : `~matplotlib.tri.Triangulation`
        The encapsulated triangulation to analyze.
    """

    def __init__(self, triangulation):
        cbook._check_isinstance(Triangulation, triangulation=triangulation)
        self._triangulation = triangulation

    @property
    def scale_factors(self):
        """
        Factors to rescale the triangulation into a unit square.

        Returns
        -------
        (float, float)
            Scaling factors (kx, ky) so that the triangulation
            ``[triangulation.x * kx, triangulation.y * ky]``
            fits exactly inside a unit square.
        """
        compressed_triangles = self._triangulation.get_masked_triangles()
        node_used = (np.bincount(np.ravel(compressed_triangles),
                                 minlength=self._triangulation.x.size) != 0)
        return (1 / np.ptp(self._triangulation.x[node_used]),
                1 / np.ptp(self._triangulation.y[node_used]))

    def circle_ratios(self, rescale=True):
        """
        Return a measure of the triangulation triangles flatness.

        The ratio of the incircle radius over the circumcircle radius is a
        widely used indicator of a triangle flatness.
        It is always ``<= 0.5`` and ``== 0.5`` only for equilateral
        triangles. Circle ratios below 0.01 denote very flat triangles.

        To avoid unduly low values due to a difference of scale between the 2
        axis, the triangular mesh can first be rescaled to fit inside a unit
        square with `scale_factors` (Only if *rescale* is True, which is
        its default value).

        Parameters
        ----------
        rescale : bool, default: True
            If True, internally rescale (based on `scale_factors`), so that the
            (unmasked) triangles fit exactly inside a unit square mesh.

        Returns
        -------
        masked array
            Ratio of the incircle radius over the circumcircle radius, for
            each 'rescaled' triangle of the encapsulated triangulation.
            Values corresponding to masked triangles are masked out.

        """
        # Coords rescaling
        if rescale:
            (kx, ky) = self.scale_factors
        else:
            (kx, ky) = (1.0, 1.0)
        pts = np.vstack([self._triangulation.x*kx,
                         self._triangulation.y*ky]).T
        tri_pts = pts[self._triangulation.triangles]
        # Computes the 3 side lengths
        a = tri_pts[:, 1, :] - tri_pts[:, 0, :]
        b = tri_pts[:, 2, :] - tri_pts[:, 1, :]
        c = tri_pts[:, 0, :] - tri_pts[:, 2, :]
        a = np.hypot(a[:, 0], a[:, 1])
        b = np.hypot(b[:, 0], b[:, 1])
        c = np.hypot(c[:, 0], c[:, 1])
        # circumcircle and incircle radii
        s = (a+b+c)*0.5
        prod = s*(a+b-s)*(a+c-s)*(b+c-s)
        # We have to deal with flat triangles with infinite circum_radius
        bool_flat = (prod == 0.)
        if np.any(bool_flat):
            # Pathologic flow
            ntri = tri_pts.shape[0]
            circum_radius = np.empty(ntri, dtype=np.float64)
            circum_radius[bool_flat] = np.inf
            abc = a*b*c
            circum_radius[~bool_flat] = abc[~bool_flat] / (
                4.0*np.sqrt(prod[~bool_flat]))
        else:
            # Normal optimized flow
            circum_radius = (a*b*c) / (4.0*np.sqrt(prod))
        in_radius = (a*b*c) / (4.0*circum_radius*s)
        circle_ratio = in_radius/circum_radius
        mask = self._triangulation.mask
        if mask is None:
            return circle_ratio
        else:
            return np.ma.array(circle_ratio, mask=mask)

    def get_flat_tri_mask(self, min_circle_ratio=0.01, rescale=True):
        """
        Eliminate excessively flat border triangles from the triangulation.

        Returns a mask *new_mask* which allows to clean the encapsulated
        triangulation from its border-located flat triangles
        (according to their :meth:`circle_ratios`).
        This mask is meant to be subsequently applied to the triangulation
        using `.Triangulation.set_mask`.
        *new_mask* is an extension of the initial triangulation mask
        in the sense that an initially masked triangle will remain masked.

        The *new_mask* array is computed recursively; at each step flat
        triangles are removed only if they share a side with the current mesh
        border. Thus no new holes in the triangulated domain will be created.

        Parameters
        ----------
        min_circle_ratio : float, default: 0.01
            Border triangles with incircle/circumcircle radii ratio r/R will
            be removed if r/R < *min_circle_ratio*.
        rescale : bool, default: True
            If True, first, internally rescale (based on `scale_factors`) so
            that the (unmasked) triangles fit exactly inside a unit square
            mesh.  This rescaling accounts for the difference of scale which
            might exist between the 2 axis.

        Returns
        -------
        bool array-like
            Mask to apply to encapsulated triangulation.
            All the initially masked triangles remain masked in the
            *new_mask*.

        Notes
        -----
        The rationale behind this function is that a Delaunay
        triangulation - of an unstructured set of points - sometimes contains
        almost flat triangles at its border, leading to artifacts in plots
        (especially for high-resolution contouring).
        Masked with computed *new_mask*, the encapsulated
        triangulation would contain no more unmasked border triangles
        with a circle ratio below *min_circle_ratio*, thus improving the
        mesh quality for subsequent plots or interpolation.
        """
        # Recursively computes the mask_current_borders, true if a triangle is
        # at the border of the mesh OR touching the border through a chain of
        # invalid aspect ratio masked_triangles.
        ntri = self._triangulation.triangles.shape[0]
        mask_bad_ratio = self.circle_ratios(rescale) < min_circle_ratio

        current_mask = self._triangulation.mask
        if current_mask is None:
            current_mask = np.zeros(ntri, dtype=bool)
        valid_neighbors = np.copy(self._triangulation.neighbors)
        renum_neighbors = np.arange(ntri, dtype=np.int32)
        nadd = -1
        while nadd != 0:
            # The active wavefront is the triangles from the border (unmasked
            # but with a least 1 neighbor equal to -1
            wavefront = (np.min(valid_neighbors, axis=1) == -1) & ~current_mask
            # The element from the active wavefront will be masked if their
            # circle ratio is bad.
            added_mask = wavefront & mask_bad_ratio
            current_mask = added_mask | current_mask
            nadd = np.sum(added_mask)

            # now we have to update the tables valid_neighbors
            valid_neighbors[added_mask, :] = -1
            renum_neighbors[added_mask] = -1
            valid_neighbors = np.where(valid_neighbors == -1, -1,
                                       renum_neighbors[valid_neighbors])

        return np.ma.filled(current_mask, True)

    def _get_compressed_triangulation(self):
        """
        Compress (if masked) the encapsulated triangulation.

        Returns minimal-length triangles array (*compressed_triangles*) and
        coordinates arrays (*compressed_x*, *compressed_y*) that can still
        describe the unmasked triangles of the encapsulated triangulation.

        Returns
        -------
        compressed_triangles : array-like
            the returned compressed triangulation triangles
        compressed_x : array-like
            the returned compressed triangulation 1st coordinate
        compressed_y : array-like
            the returned compressed triangulation 2nd coordinate
        tri_renum : int array
            renumbering table to translate the triangle numbers from the
            encapsulated triangulation into the new (compressed) renumbering.
            -1 for masked triangles (deleted from *compressed_triangles*).
        node_renum : int array
            renumbering table to translate the point numbers from the
            encapsulated triangulation into the new (compressed) renumbering.
            -1 for unused points (i.e. those deleted from *compressed_x* and
            *compressed_y*).

        """
        # Valid triangles and renumbering
        tri_mask = self._triangulation.mask
        compressed_triangles = self._triangulation.get_masked_triangles()
        ntri = self._triangulation.triangles.shape[0]
        tri_renum = self._total_to_compress_renum(tri_mask, ntri)

        # Valid nodes and renumbering
        node_mask = (np.bincount(np.ravel(compressed_triangles),
                                 minlength=self._triangulation.x.size) == 0)
        compressed_x = self._triangulation.x[~node_mask]
        compressed_y = self._triangulation.y[~node_mask]
        node_renum = self._total_to_compress_renum(node_mask)

        # Now renumbering the valid triangles nodes
        compressed_triangles = node_renum[compressed_triangles]

        return (compressed_triangles, compressed_x, compressed_y, tri_renum,
                node_renum)

    @staticmethod
    def _total_to_compress_renum(mask, n=None):
        """
        Parameters
        ----------
        mask : 1d bool array or None
            mask
        n : int
            length of the mask. Useful only id mask can be None

        Returns
        -------
        int array
            array so that (`valid_array` being a compressed array
            based on a `masked_array` with mask *mask*):

            - For all i such as mask[i] = False:
              valid_array[renum[i]] = masked_array[i]
            - For all i such as mask[i] = True:
              renum[i] = -1 (invalid value)
        """
        if n is None:
            n = np.size(mask)
        if mask is not None:
            renum = np.full(n, -1, dtype=np.int32)  # Default num is -1
            valid = np.arange(n, dtype=np.int32)[~mask]
            renum[valid] = np.arange(np.size(valid, 0), dtype=np.int32)
            return renum
        else:
            return np.arange(n, dtype=np.int32)
