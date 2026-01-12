def test__debug_mock_firestore_types(mock_firestore):
    a, b = mock_firestore
    print("mock_firestore types:", type(a), type(b))
